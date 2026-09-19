"""회장명 요미가나(`hospitals.name_kana`) 칼럼 추가 · 초기값 채우기.

    python -m scripts.migrate_hospital_kana            # 무엇이 바뀌는지만 본다
    python -m scripts.migrate_hospital_kana --apply    # 실제로 옮긴다

왜 필요한가
-----------
회장명이 한자·가타카나라 「さんぷる」로는 サンプル会館 A 를 찾을 수 없다.
그동안 관리 화면(`frontend/assets/js/admin/views/hospitals.js`)이 회장 20件의
읽기를 **화면 파일에 박아** 두고 있었다.

    var READINGS = { V01: 'さんぷるかいかん えー …', … };

그 파일의 주석도 「장기적으로는 hospitals 에 name_kana 를 두는 편이 옳다」고
적어 두었다. 화면에 두면

  · 회장이 바뀔 때마다 코드를 고쳐야 한다 (담당자가 할 수 없는 일이다)
  · 검색 화면을 하나 더 만들면 그 표도 복사해야 한다

읽기는 회장에 딸린 사실이므로 DB 에 둔다. 이 스크립트는 칼럼을 만들고,
화면에 박혀 있던 값을 **초기값으로 한 번만** 옮겨 넣는다. 그 뒤로는
관리 화면의 「회장 관리」 표에서 담당자가 직접 고친다.

비어 있어도 괜찮다
------------------
요미가나가 없는 회장은 한자·코드·지역·주소로만 걸린다. 검색이 조금 불편할
뿐 화면이 깨지지는 않는다. 그래서 **이미 값이 있는 행은 件드리지 않는다** —
담당자가 고쳐 둔 값을 이 스크립트가 되돌리면 안 된다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)

import argparse
import sys

from sqlalchemy import select, text

from app.core.database import SessionLocal, engine
from app.models.hospital import Hospital

# 화면(`hospitals.js`)에 박혀 있던 값. 코드 → 요미가나(히라가나).
# 회장명 읽기 + 지역 읽기를 띄어쓰기로 이어 두었다. 검색은 부분 일치라
# 「さんぷる」로도, 「みなとく」로도 걸린다.
READINGS = {
    "V01": "さんぷるかいかん えー とうきょうと みなとく",
    "V02": "さんぷるかいかん びー とうきょうと すみだく",
    "V03": "さんぷるかいかん しー とうきょうと ちよだく",
    "V04": "さんぷるかいかん でぃー とうきょうと しんじゅくく",
    "V05": "さんぷるかいかん いー とうきょうと ちよだく",
    "V06": "さんぷるかいかん えふ とうきょうと しんじゅくく",
    "V07": "さんぷるかいかん じー おおさかふ おおさかし ちゅうおうく",
    "V08": "さんぷるかいかん えいち おおさかふ おおさかし なにわく",
    "V09": "さんぷるかいかん あい おおさかふ おおさかし あべのく",
    "V10": "さんぷるかいかん じぇー きょうとふ きょうとし きたく",
    "V11": "さんぷるかいかん けー きょうとふ きょうとし ひがしやまく",
    "V12": "さんぷるかいかん える きょうとふ きょうとし しもぎょうく",
    "V13": "さんぷるかいかん えむ ひょうごけん ひめじし",
    "V14": "さんぷるかいかん えぬ あいちけん なごやし なかく",
    "V15": "さんぷるかいかん おー ひろしまけん ひろしまし なかく",
    "V16": "さんぷるかいかん ぴー みやぎけん せんだいし あおばく",
    "V17": "さんぷるかいかん きゅー かながわけん よこはまし にしく",
    "V18": "さんぷるかいかん あーる ふくおかけん ふくおかし さわらく",
    "V19": "さんぷるかいかん えす おきなわけん なはし",
    "V20": "さんぷるかいかん てぃー ならけん ならし",
}

COLUMN_SQL = (
    "ALTER TABLE hospitals "
    "ADD COLUMN name_kana VARCHAR(200) NOT NULL DEFAULT '' "
    "COMMENT '회장명 요미가나 (검색용)' AFTER name"
)


def has_column(db, table: str, column: str) -> bool:
    row = db.execute(
        text(
            "SELECT 1 FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ),
        {"t": table, "c": column},
    ).first()
    return row is not None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="会場名フリガナのカラム追加・初期値の取り込み")
    parser.add_argument("--apply", action="store_true", help="実際に反映する")
    args = parser.parse_args(argv)

    print("=" * 70)
    print(" 会場名フリガナ(name_kana) マイグレーション")
    print("=" * 70)

    db = SessionLocal()
    try:
        exists = has_column(db, "hospitals", "name_kana")

        if exists:
            print("  カラム : すでにあります。")
        elif args.apply:
            db.execute(text(COLUMN_SQL))
            db.commit()
            print("  カラム : hospitals.name_kana を作成しました。")
        else:
            print("  カラム : ありません。--apply を付けると作成します。")
            print(f"         {COLUMN_SQL}")
            # 칼럼이 없으면 아래의 값 채우기를 미리 볼 수 없다.
            # 무엇을 넣을 것인지만 세어서 보여 준다.
            print("-" * 70)
            print(f"  値の取り込み : 表に用意された読み {len(READINGS)}件")
            print("=" * 70)
            return 0

        hospitals = db.execute(
            select(Hospital).order_by(Hospital.sort_order, Hospital.id)
        ).scalars().all()

        filled = skipped_has_value = skipped_unknown = 0

        print("-" * 70)
        for h in hospitals:
            reading = READINGS.get(h.code.upper())

            # 담당자가 이미 고쳐 둔 값을 되돌리지 않는다.
            if (h.name_kana or "").strip():
                skipped_has_value += 1
                continue

            if not reading:
                skipped_unknown += 1
                print(f"  スキップ : {h.code} {h.name} — 用意された読みがありません")
                continue

            print(f"  取り込み : {h.code} {h.name} → {reading}")
            if args.apply:
                h.name_kana = reading
            filled += 1

        if args.apply:
            db.commit()

        print("-" * 70)
        print(f"  対象の会場   : {filled}件")
        print(f"  値が入り済み : {skipped_has_value}件")
        print(f"  読みが不明   : {skipped_unknown}件 (管理画面から直接入力してください)")

        if not args.apply:
            print()
            print("  ※ まだ反映していません。--apply を付けて実行し直してください。")

        print("=" * 70)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
