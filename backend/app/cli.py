"""Administration commands.

  python -m app.cli create-admin --email admin@example.com --name "Admin"   (asks for the password)
  python -m app.cli purge --days 30        delete events/attempts older than 30 days, expired sessions
  python -m app.cli erase-user --email someone@example.com
"""
import argparse
import getpass
import secrets
import sys

from .config import get_settings
from .database import init_db, make_engine, make_session_factory
from .models import User
from .security import hash_password
from .services.privacy import erase_user, purge_old
from .services.templates import TemplateStore


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("create-admin"); a.add_argument("--email", required=True); a.add_argument("--name", required=True)
    p = sub.add_parser("purge"); p.add_argument("--days", type=int, required=True)
    e = sub.add_parser("erase-user"); e.add_argument("--email", required=True)
    args = ap.parse_args()

    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(s.db_url)
    init_db(engine)
    with make_session_factory(engine)() as db:
        if args.cmd == "create-admin":
            pw = getpass.getpass("Password: ")
            if len(pw) < s.min_password_length or pw != getpass.getpass("Repeat: "):
                print(f"Passwords must match and be at least {s.min_password_length} characters.")
                return 1
            if db.query(User).filter_by(email=args.email.lower()).first():
                print("That email already exists.")
                return 1
            db.add(User(full_name=args.name, email=args.email.lower(), account_number="AD" + secrets.token_hex(5).upper(),
                        password_hash=hash_password(pw), role="admin"))
            db.commit()
            print("Admin created.")
        elif args.cmd == "purge":
            print(purge_old(db, args.days))
        elif args.cmd == "erase-user":
            u = db.query(User).filter_by(email=args.email.lower()).one_or_none()
            if not u:
                print("No such user.")
                return 1
            erase_user(db, TemplateStore(s.templates_dir, s.template_key), u)
            print("User erased.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
