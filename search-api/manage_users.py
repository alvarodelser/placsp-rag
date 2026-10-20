"""Who may use the app (invite-only): the allowed emails, and the accounts made from them.

  python manage_users.py allow EMAIL [NOTE]   let EMAIL create an account (and sign in)
  python manage_users.py remove EMAIL         take EMAIL off the list: no sign-in, no new tokens
  python manage_users.py list                 the allowed emails, whether each has registered, and the
                                              accounts not on the list (no access until allowed)

Reads the same database as the API (USERS_DB, default users.db). In the container:
  docker compose exec placsp-search-api python manage_users.py allow persona@ejemplo.es
"""
import os
import sys

import users


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("allow", "remove", "list") or (argv[1] != "list" and len(argv) < 3):
        print(__doc__.strip())
        return 2
    conn = users.connect(os.getenv("USERS_DB", "users.db"))
    try:
        cmd = argv[1]
        if cmd == "allow":
            email = argv[2].strip().lower()
            if "@" not in email:
                print(f"not an email: {email}")
                return 2
            users.allow_email(conn, email, " ".join(argv[3:]) or None)
            print(f"allowed: {email}")
        elif cmd == "remove":
            print(("removed: " if users.disallow_email(conn, argv[2]) else "was not on the list: ") + argv[2].strip().lower())
        else:
            rows = users.list_allowed(conn)
            for r in rows:
                state = f"registered {r['registered_at'][:10]} as {r['display_name']}" if r["registered_at"] else "not registered yet"
                print(f"{r['email']:40} {state}{'  · ' + r['note'] if r['note'] else ''}")
            print(f"{len(rows)} allowed")
            outside = conn.execute("SELECT email, display_name FROM users WHERE email NOT IN"
                                   " (SELECT email FROM allowed_emails) ORDER BY email").fetchall()
            if outside:
                print(f"\n{len(outside)} accounts without access (allow them to let them back in):")
                for r in outside:
                    print(f"  {r['email']:38} {r['display_name']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
