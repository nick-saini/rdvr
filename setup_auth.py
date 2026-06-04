"""
setup_auth.py — Run this once to set the admin password.
Usage:  python setup_auth.py
        python setup_auth.py --username admin --password MySecret123
"""
import sys
import os
import configparser
import getpass
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auth import hash_password

INI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

def main():
    parser = argparse.ArgumentParser(description="Set SentinelDesk admin credentials")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    username = args.username or input("Username [admin]: ").strip() or "admin"
    if args.password:
        password = args.password
    else:
        password = getpass.getpass("Password: ")
        confirm  = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("ERROR: passwords do not match.")
            sys.exit(1)

    if len(password) < 8:
        print("ERROR: password must be at least 8 characters.")
        sys.exit(1)

    hashed = hash_password(password)

    cfg = configparser.ConfigParser()
    cfg.read(INI, encoding="utf-8")
    if "auth" not in cfg:
        cfg["auth"] = {}
    cfg["auth"]["username"]      = username
    cfg["auth"]["password_hash"] = hashed

    with open(INI, "w", encoding="utf-8") as f:
        cfg.write(f)

    print(f"✓ Credentials saved for user '{username}'")
    print(f"  Config: {INI}")

if __name__ == "__main__":
    main()
