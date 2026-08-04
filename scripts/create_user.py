"""Script CLI pour creer un compte utilisateur jurIA.

Usage:
    python scripts/create_user.py --username alice --password secret
    python scripts/create_user.py --username alice --password secret --display-name "Alice D."
"""

import argparse
import sys
import os

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from juria.auth import create_user_db, get_user_db


def main():
    parser = argparse.ArgumentParser(description="Creer un utilisateur jurIA")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name", default=None)
    args = parser.parse_args()

    display_name = args.display_name or args.username

    if get_user_db(args.username):
        print(f"Erreur : l'utilisateur '{args.username}' existe deja.")
        sys.exit(1)

    create_user_db(args.username, args.password, display_name)
    print(f"Utilisateur '{args.username}' cree avec succes.")


if __name__ == "__main__":
    main()
