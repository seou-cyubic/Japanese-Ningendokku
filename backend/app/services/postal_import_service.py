"""우편번호(주소) 데이터 적재 — 일본우편 KEN_ALL.

「주소 찾기」(U-14)가 이 데이터 위에서 돈다. 넣지 않으면 검색이
**조용히 0건**을 돌려준다. 화면에도 로그에도 원인이 남지 않아, 「검색해도
아무것도 안 나온다」는 문의가 들어와야 비로소 알게 된다. 그 구멍을 막기
위해 적재 로직을 스크립트에서 여기로 끌어올렸다.

부르는 곳이 둘이다.

    scripts/import_postal_codes.py   담당자가 손으로 (CLI)
    app/main.py 의 lifespan          서버가 뜰 때 자동으로

같은 일을 두 곳에 적어 두면 한쪽만 고치게 된다. 판정 기준(무엇을
「적재됨」으로 볼 것인가)이 특히 그렇다.

왜 「0건」이 아니라 「임계값 미만」인가
--------------------------------------
적재 도중에 서버가 죽으면 3만 건쯤 들어간 상태로 남는다. 0건이 아니므로
「있다」고 판정하면 그 반쪽짜리 데이터로 계속 돈다. 전체가 12만 건 남짓이니
10만 건을 밑돌면 온전하지 않은 것으로 본다.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import ssl
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.core.database import engine
from app.models.postal_code import PostalCode

logger = logging.getLogger("kenshin")

# 일본우편 공식 배포처. 2025년에 주소가 /service/search/zipcode/ 아래로 옮겨졌다.
KEN_ALL_URL = (
    "https://www.post.japanpost.jp/service/search/zipcode/download/utf/zip/utf_ken_all.zip"
)

# 정역 칸이 주소가 아니라 설명인 경우
NOT_A_TOWN = re.compile(r"以下に掲載がない場合|の次に番地がくる場合|^一円$")

# 「芝公園（１〜３丁目）」의 괄호 부분. 전각·반각 모두 받는다.
PAREN = re.compile(r"[（(].*?[）)]")

# 카나 쪽 괄호도 같이 떼어 낸다. 한자 쪽과 **같은 결과**가 되어야 한다 —
# `芝公園（１〜３丁目）` → `芝公園` 이면 카나도 `ｼﾊﾞｺｳｴﾝ` 여야 한다.
#
# 예전 식은 `[（(].*?[）)]|[ｦ-ﾟ]*\([^)]*\)` 였는데, 두 번째 갈래의 `[ｦ-ﾟ]*` 가
# 괄호 **앞의 카나까지** 먹었다. `ｵｵﾄﾞｵﾘﾆｼ(1-19ﾁｮｳﾒ)` 가 통째로 지워져
# 정역 읽기가 사라졌고, 카나로 「おおどおりにし」를 쳐도 걸리지 않았다.
PAREN_KANA = re.compile(r"[（(][^）)]*[）)]")

# 12만 건을 한 번에 넣으면 메모리와 패킷 크기에서 걸린다. 나눠 넣는다.
CHUNK = 2000

# 여러 워커가 동시에 뜰 때 하나만 적재하게 하는 자물쇠 이름.
IMPORT_LOCK_NAME = "kenshin_postal_import"


class PostalImportError(Exception):
    """적재를 끝내지 못한 이유. 서버를 멈추지는 않는다."""


# --------------------------------------------------------------------------
# 진행 상태
# --------------------------------------------------------------------------
# 관리 화면이 「지금 어떤 상태인가」를 물을 수 있어야 한다. 로그만 남기면
# 담당자는 서버 콘솔을 볼 수 없어 영영 모른다.

MISSING = "MISSING"      # 데이터가 없거나 온전하지 않다
RUNNING = "RUNNING"      # 지금 적재 중
READY = "READY"          # 쓸 수 있다
FAILED = "FAILED"        # 적재를 시도했으나 실패했다
DISABLED = "DISABLED"    # 자동 적재를 꺼 두었고, 데이터도 없다


@dataclass
class ImportState:
    state: str = MISSING
    count: int = 0
    total: int = 0
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "count": self.count,
            "total": self.total,
            "message": self.message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


# 프로세스 하나의 현재 상태. 워커를 여러 개 띄우면 워커마다 따로 갖지만,
# 어느 워커가 답하든 `count` 는 DB 에서 다시 세므로 어긋나지 않는다.
STATE = ImportState()


@dataclass
class LoadResult:
    inserted: int = 0
    deleted: int = 0
    total: int = 0
    source: str = ""
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# 조회
# --------------------------------------------------------------------------


def ensure_table() -> None:
    """테이블이 없으면 만든다. `init_db` 를 아직 돌리지 않은 환경 대비."""
    PostalCode.__table__.create(bind=engine, checkfirst=True)


def count(db: Session) -> int:
    return db.execute(select(func.count()).select_from(PostalCode)).scalar() or 0


def is_loaded(db: Session, minimum: int) -> bool:
    """쓸 만큼 들어 있는가. 판정 기준을 한 곳에 둔다."""
    return count(db) >= max(1, minimum)


def sample(db: Session, zipcode: str) -> PostalCode | None:
    """적재가 제대로 됐는지 눈으로 확인할 한 건."""
    return db.execute(
        select(PostalCode).where(PostalCode.zipcode == zipcode)
    ).scalars().first()


def status(db: Session) -> dict:
    """관리 화면과 헬스 체크가 읽는 현재 상태."""
    STATE.count = count(db)
    # 적재가 끝난 뒤에 다시 물으면 DB 가 정답이다. 프로세스가 재시작되면
    # STATE 는 초기값이지만 데이터는 남아 있다.
    if STATE.state in (MISSING, DISABLED) and STATE.count:
        STATE.state = READY
    return STATE.as_dict()


# --------------------------------------------------------------------------
# 원본 읽기
# --------------------------------------------------------------------------


def fetch_csv(source: Path | None, *, log: Callable[[str], None] = logger.info) -> str:
    """CSV 본문을 문자열로 얻는다. 파일을 주면 그것을, 아니면 내려받는다."""
    if source is not None:
        log(f"郵便番号の元データをファイルから読み込みます : {source}")
        try:
            return Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            raise PostalImportError(f"ファイルを読み込めませんでした : {source} ({exc})") from exc

    log(f"郵便番号元データをダウンロードする : {KEN_ALL_URL}")
    # Windows Python 에서 로컬 CA 인증서를 못 찾는 문제 대응
    try:
        import certifi  # noqa: F811
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        # certifi 없이 시스템 기본 인증서 사용 (Windows에서 실패할 수 있음)
        ssl_ctx = ssl.create_default_context()
        logger.warning("certifi パッケージがないため、システム既定の CA を使用します。")
    try:
        with urllib.request.urlopen(KEN_ALL_URL, timeout=120, context=ssl_ctx) as res:
            blob = res.read()
    except Exception as exc:  # noqa: BLE001 — URLError·타임아웃·SSL 등 전부
        raise PostalImportError(
            "日本郵便から郵便番号データをダウンロードできませんでした。"
            f"インターネット接続を確認してください。 ({exc})"
        ) from exc

    log(f"受信サイズ : {len(blob):,} バイト")

    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
        name = archive.namelist()[0]
        return archive.read(name).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise PostalImportError(
            "ダウンロードしたファイルを開けませんでした。日本郵便の配信形式が"
            f"変更された可能性があります。 ({exc})"
        ) from exc


def clean_town(town: str) -> str:
    """정역 칸에서 주소가 아닌 부분을 걷어낸다.

    원본에는 「以下に掲載がない場合」처럼 사람이 읽으라고 넣은 말이 섞여 있다.
    그대로 두면 검색 결과에 그것이 나와 이용자가 고른다.
    """
    town = town.strip()
    if NOT_A_TOWN.search(town):
        return ""
    return PAREN.sub("", town).strip()


# 카나 쪽에서도 「사람이 읽으라고 넣은 말」을 걷어낸다.
#
# 전각·반각을 둘 다 본다. KEN_ALL 의 **utf 판은 카나 칸이 반각**
# (`ｲｶﾆｹｲｻｲｶﾞﾅｲﾊﾞｱｲ`)인데, 예전 코드는 전각(`イカニケイサイガナイバアイ`)만
# 보고 있어 한 건도 걸리지 않았다. 한자 칸(`clean_town`)에서는 지워지는데
# 카나 칸에는 그대로 남아, 카나로 검색하면 「以下に掲載がない場合」이 걸렸다.
_NOT_A_TOWN_KANA = (
    "イカニケイサイガナイバアイ", "ｲｶﾆｹｲｻｲｶﾞﾅｲﾊﾞｱｲ",
    "ノツギニバンチガクルバアイ", "ﾉﾂｷﾞﾆﾊﾞﾝﾁｶﾞｸﾙﾊﾞｱｲ",
)
_ICHIEN_KANA = ("イチエン", "ｲﾁｴﾝ")


def clean_town_kana(kana: str) -> str:
    kana = kana.strip()
    if any(mark in kana for mark in _NOT_A_TOWN_KANA):
        return ""
    if kana in _ICHIEN_KANA:
        return ""
    return PAREN_KANA.sub("", kana).strip()


def parse(csv_text: str) -> list[dict]:
    """CSV 를 읽어 중복 없는 주소 목록으로 만든다.

    원본 형식 (15열, 헤더 없음)
        0 전국지방공공단체코드  1 (구)우편번호 5자리  2 우편번호 7자리
        3 도도부현 카나         4 시구정촌 카나       5 정역 카나
        6 도도부현             7 시구정촌            8 정역
    """
    seen: set[tuple[str, str, str, str]] = set()
    rows: list[dict] = []

    for r in csv.reader(io.StringIO(csv_text)):
        if len(r) < 9:
            continue

        zipcode = r[2].strip()
        if len(zipcode) != 7 or not zipcode.isdigit():
            continue

        pref, city = r[6].strip(), r[7].strip()
        town = clean_town(r[8])

        key = (zipcode, pref, city, town)
        if key in seen:
            continue
        seen.add(key)

        pref_kana, city_kana = r[3].strip(), r[4].strip()
        town_kana = clean_town_kana(r[5])

        rows.append({
            "zipcode": zipcode,
            "prefecture": pref,
            "city": city,
            "town": town,
            "prefecture_kana": pref_kana,
            "city_kana": city_kana,
            "town_kana": town_kana,
            "search_text": f"{pref}{city}{town}",
            "search_kana": f"{pref_kana}{city_kana}{town_kana}",
        })

    return rows


# --------------------------------------------------------------------------
# 적재
# --------------------------------------------------------------------------


def _acquire_lock():
    """다른 워커가 이미 적재 중이면 None. 잡았으면 잠금을 쥔 커넥션.

    워커를 여러 개 띄우면 전부 같은 판정을 하고 전부 12만 건을 넣으려 든다.
    결과는 같지만(마지막에 지우고 다시 넣으므로) 그동안 DB 가 잠긴다.

    **잠금은 전용 커넥션에 건다.** MySQL 의 `GET_LOCK` 은 커넥션(세션)에
    붙는데, ORM Session 은 커밋할 때마다 커넥션을 풀에 돌려준다. 예전에는
    Session 으로 잡았다가 청크마다 커밋한 뒤 **다른 커넥션에서** 풀려고 해서
    해제가 되지 않았다. 풀에 남은 커넥션이 잠금을 계속 쥐어, 기동 시 자동
    적재 이후 관리 화면의 「再取り込み」가 늘 「他の処理が取り込み中です」가 됐다.

    MySQL 이 아닌 곳에서는 자물쇠가 없으므로 빈 커넥션을 돌려준다 —
    단일 프로세스 개발 환경이다.
    """
    conn = engine.connect()
    try:
        got = conn.execute(
            text("SELECT GET_LOCK(:name, 0)"), {"name": IMPORT_LOCK_NAME}
        ).scalar()
    except Exception:  # noqa: BLE001
        return conn
    if got:
        return conn
    conn.close()
    return None


def _release_lock(conn) -> None:
    try:
        conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": IMPORT_LOCK_NAME})
    except Exception:  # noqa: BLE001
        pass
    finally:
        conn.close()


def load(
    db: Session,
    *,
    reset: bool = False,
    source: Path | None = None,
    minimum: int = 0,
    log: Callable[[str], None] = logger.info,
    progress: Callable[[int, int], None] | None = None,
) -> LoadResult:
    """우편번호 데이터를 적재한다. 몇 번을 돌려도 결과가 같다(멱등).

    `reset=False` 이고 이미 `minimum` 이상 들어 있으면 아무것도 하지 않는다.
    """
    ensure_table()

    existing = count(db)
    result = LoadResult(total=existing, source=str(source) if source else KEN_ALL_URL)

    if not reset and minimum and existing >= minimum:
        result.skipped = True
        log(f"郵便番号データが既に {existing:,}件存在する。取り込みをスキップする。")
        return result

    lock = _acquire_lock()
    if lock is None:
        result.skipped = True
        result.warnings.append("他の処理が取り込み中です。")
        log("他のプロセスが郵便番号を取り込み中だ。このプロセスはスキップする。")
        return result

    try:
        csv_text = fetch_csv(source, log=log)
        rows = parse(csv_text)
        log(f"整理後 : {len(rows):,}件（重複・説明行を除外）")

        if not rows:
            raise PostalImportError(
                "元データから住所を1件も読み取れなかった。ファイル形式を確認すること。"
            )

        # 지우고 넣는 사이에 검색이 들어오면 결과가 빈다. 짧은 순간이고,
        # 애초에 데이터가 없을 때 도는 경로라 실질적인 영향은 없다.
        if existing:
            db.execute(delete(PostalCode))
            db.commit()
            result.deleted = existing
            log(f"既存の {existing:,}件を削除")

        for i in range(0, len(rows), CHUNK):
            db.execute(PostalCode.__table__.insert(), rows[i:i + CHUNK])
            db.commit()
            done = min(i + CHUNK, len(rows))
            if progress:
                progress(done, len(rows))

        result.inserted = len(rows)
        result.total = count(db)
        log(f"郵便番号取り込み完了 : {result.total:,}件")
        return result
    finally:
        _release_lock(lock)


# --------------------------------------------------------------------------
# 서버 기동 시
# --------------------------------------------------------------------------


def run_startup_import(session_factory, *, auto: bool, minimum: int, source: str) -> None:
    """기동 시 호출한다. **블로킹이다** — 부르는 쪽이 스레드로 돌린다.

    실패해도 예외를 밖으로 내보내지 않는다. 주소 검색이 안 되는 것과
    서버가 안 뜨는 것은 심각도가 전혀 다르다.
    """
    db = session_factory()
    try:
        ensure_table()
        existing = count(db)

        if existing >= minimum:
            STATE.state = READY
            STATE.count = existing
            STATE.message = f"郵便番号 {existing:,}件"
            logger.info("郵便番号データを確認 — %s件。住所検索がご利用いただけます。",
                        f"{existing:,}")
            return

        if not auto:
            STATE.state = DISABLED
            STATE.count = existing
            STATE.message = (
                "郵便番号データがないため「住所検索」が動作しません。 "
                "POSTAL_AUTO_IMPORT=true に設定するか、 "
                "python -m scripts.import_postal_codes を実行してください。"
            )
            logger.warning("%s (現在 %s件)", STATE.message, f"{existing:,}")
            return

        STATE.state = RUNNING
        STATE.count = existing
        STATE.started_at = datetime.now()
        STATE.message = "郵便番号データを取り込み中です。1～2分ほどかかります。"
        logger.warning(
            "郵便番号データが %s件しかありません(基準 %s件)。自動取り込みを開始します — "
            "1～2分かかり、その間は「住所検索」が動作しません。",
            f"{existing:,}", f"{minimum:,}",
        )

        result = load(
            db,
            reset=True,
            source=Path(source) if source else None,
            log=logger.info,
            progress=_log_progress,
        )

        if result.skipped:
            # 다른 워커가 하고 있다. 그쪽이 끝내면 다음 조회에서 READY 가 된다.
            STATE.state = MISSING
            STATE.message = "他の処理が取り込み中です。"
            return

        STATE.state = READY
        STATE.count = result.total
        STATE.finished_at = datetime.now()
        STATE.message = f"郵便番号 {result.total:,}件を取り込みました。"
        logger.info("郵便番号の自動取り込み完了 — %s件", f"{result.total:,}")

    except Exception as exc:  # noqa: BLE001 — 적재 실패로 서버를 멈추지 않는다
        db.rollback()
        STATE.state = FAILED
        STATE.finished_at = datetime.now()
        STATE.message = str(exc)
        logger.exception(
            "郵便番号の自動取り込みに失敗しました。「住所検索」が動作しません。 "
            "python -m scripts.import_postal_codes で直接取り込んでください。"
        )
    finally:
        db.close()


_last_logged = 0


def _log_progress(done: int, total: int) -> None:
    """10% 단위로만 남긴다. 2,000건마다 찍으면 로그가 60줄이 된다."""
    global _last_logged
    step = max(1, total // 10)
    if done >= _last_logged + step or done >= total:
        _last_logged = done
        logger.info("郵便番号の取り込み中 : %s / %s", f"{done:,}", f"{total:,}")
        if done >= total:
            _last_logged = 0
