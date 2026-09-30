"""이용자 화면 입장 계정(site_users) 관리.

    python -m scripts.site_users list
    python -m scripts.site_users add <ID> [--name 説明]      # 비밀번호는 물어본다
    python -m scripts.site_users passwd <ID>                 # 비밀번호 변경
    python -m scripts.site_users disable <ID>                # 로그인 · 기존 세션 차단
    python -m scripts.site_users enable <ID>

비밀번호는 화면에 표시하지 않고 입력받는다(getpass). 자동화에서 쓸 때만
`--password <値>` 로 넘길 수 있다 — 셸 기록에 남으므로 평소에는 쓰지 않는다.
DB 에는 bcrypt 해시만 저장한다.
"""

import scripts._console  # noqa: F401  (콘솔 UTF-8 보정)
import argparse
import getpass
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.site_user import SiteUser
from app.services import site_auth_service

MIN_PASSWORD = 8


def _read_password(given: str | None) -> str:
    if given is not None:
        password = given
    else:
        password = getpass.getpass("新しいパスワード: ")
        if getpass.getpass("もう一度入力: ") != password:
            raise SystemExit("パスワードが一致しません。")
    if len(password) < MIN_PASSWORD:
        raise SystemExit(f"パスワードは{MIN_PASSWORD}文字以上にしてください。")
    return password


def _find(db, login_id: str) -> SiteUser:
    user = db.execute(
        select(SiteUser).where(SiteUser.login_id == login_id)
    ).scalar_one_or_none()
    if user is None:
        raise SystemExit(f"アカウント {login_id} が見つかりません。")
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="利用者画面アカウントの管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="一覧")

    add = sub.add_parser("add", help="追加")
    add.add_argument("login_id")
    add.add_argument("--name", default="")
    add.add_argument("--password")

    passwd = sub.add_parser("passwd", help="パスワード変更")
    passwd.add_argument("login_id")
    passwd.add_argument("--password")

    for name in ("disable", "enable"):
        sub.add_parser(name, help="利用停止" if name == "disable" else "利用再開") \
           .add_argument("login_id")

    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if args.command == "list":
            users = db.execute(select(SiteUser).order_by(SiteUser.login_id)).scalars().all()
            if not users:
                print("アカウントがありません。")
            for u in users:
                state = "有効" if u.is_active else "停止"
                last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "-"
                print(f"  {u.login_id:<16} {state}  最終ログイン {last}  {u.name}")
            return 0

        if args.command == "add":
            exists = db.execute(
                select(SiteUser).where(SiteUser.login_id == args.login_id)
            ).scalar_one_or_none()
            if exists:
                raise SystemExit(f"アカウント {args.login_id} はすでにあります。")
            db.add(SiteUser(
                login_id=args.login_id,
                password_hash=hash_password(_read_password(args.password)),
                name=args.name,
                is_active=True,
            ))
            db.commit()
            print(f"アカウント {args.login_id} を追加しました。")
            return 0

        user = _find(db, args.login_id)

        if args.command == "passwd":
            user.password_hash = hash_password(_read_password(args.password))
            # 옛 비밀번호로 들어와 있던 사람도 끊는다
            ended = site_auth_service.end_sessions_of(db, user.id)
            db.commit()
            print(f"{user.login_id} のパスワードを変更しました。"
                  f"（ログイン中のセッション {ended}件を終了）")
        else:
            user.is_active = args.command == "enable"
            ended = 0 if user.is_active else site_auth_service.end_sessions_of(db, user.id)
            db.commit()
            print(f"{user.login_id} を{'有効' if user.is_active else '停止'}にしました。"
                  + (f"（ログイン中のセッション {ended}件を終了）" if ended else ""))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
