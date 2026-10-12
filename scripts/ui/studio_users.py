"""Manage the Studio's remote-access accounts (config/studio_users.json, git-ignored).

    python scripts/ui/studio_users.py add andy --role admin      # asks for the password twice
    python scripts/ui/studio_users.py add sofia                  # role editor (matching only)
    python scripts/ui/studio_users.py passwd andy
    python scripts/ui/studio_users.py role sofia admin
    python scripts/ui/studio_users.py remove sofia
    python scripts/ui/studio_users.py list
    python scripts/ui/studio_users.py sessions                   # who is signed in
    python scripts/ui/studio_users.py signout andy               # end every session of an account

Roles: editor (matching) and admin (also builds, the level setting and data import/export). No role can
install into or restore the game remotely: that stays on the host computer's own Studio address.

Passwords are read from the terminal (never from the command line, so they stay out of shell history) and
stored as scrypt hashes. Changing a password or role, or removing an account, ends its sessions at once.
STUDIO_PASSWORD may supply the password for scripted setups and tests.
"""
import argparse
import datetime as dt
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common.env import REPO_ROOT  # noqa: E402
from studio_auth import (ROLES, SessionStore, UserStore, check_password_strength, check_username,  # noqa: E402
                         hash_password)
from studio_net import load_server_config  # noqa: E402


def ask_password(name):
    env = os.environ.get("STUDIO_PASSWORD")
    if env:
        return check_password_strength(env, name)
    first = getpass.getpass(f"Password for {name}: ")
    check_password_strength(first, name)
    if getpass.getpass("Again: ") != first:
        raise SystemExit("the passwords differ; nothing changed")
    return first


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REPO_ROOT)
    ap.add_argument("--config", type=Path, help="server config (default config/studio_server.json)")
    ap.add_argument("--state-dir", type=Path, help="TESTS: the server's --state-dir (where the sessions are)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("name")
    a.add_argument("--role", choices=ROLES, default="editor")
    sub.add_parser("passwd").add_argument("name")
    r = sub.add_parser("role")
    r.add_argument("name")
    r.add_argument("role", choices=ROLES)
    sub.add_parser("remove").add_argument("name")
    sub.add_parser("list")
    sub.add_parser("sessions")
    sub.add_parser("signout").add_argument("name")
    args = ap.parse_args()

    over = {"sessions_file": str((args.state_dir / "sessions.sqlite").resolve())} if args.state_dir else {}
    cfg = load_server_config(args.root, args.config, over)
    store = UserStore(cfg["users_path"])
    sessions = SessionStore(cfg["sessions_path"], cfg["session"]["idle_hours"], cfg["session"]["max_days"])
    users = store.users()
    now = dt.datetime.now().isoformat(timespec="seconds")
    try:
        if args.cmd == "add":
            name = check_username(args.name)
            if name in users:
                raise SystemExit(f"{name} exists; use passwd or role")
            users[name] = {"role": args.role, "password": hash_password(ask_password(name)), "changed_at": now}
            store.write(users)
            print(f"added {name} ({args.role}) to {store.path}")
        elif args.cmd in ("passwd", "role", "remove", "signout"):
            name = args.name
            if name not in users:
                raise SystemExit(f"no account {name}")
            if args.cmd == "passwd":
                users[name].update(password=hash_password(ask_password(name)), changed_at=now)
            elif args.cmd == "role":
                users[name].update(role=args.role, changed_at=now)
            elif args.cmd == "remove":
                del users[name]
            if args.cmd != "signout":
                store.write(users)
            ended = sessions.delete_user(name)
            print(f"{args.cmd}: {name} done; {ended} session(s) ended")
        elif args.cmd == "list":
            for name, u in sorted(users.items()):
                print(f"{name:20} {u['role']:7} changed {u.get('changed_at', '?')}")
            if not users:
                print(f"no accounts yet ({store.path}); add one with: studio_users.py add <name> --role admin")
        elif args.cmd == "sessions":
            for s in sessions.active():
                seen = dt.datetime.fromtimestamp(s["last_seen"]).isoformat(timespec="seconds")
                print(f"{s['username']:20} from {s['address'] or '?':16} last seen {seen}")
    except ValueError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
