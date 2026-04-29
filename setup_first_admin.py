"""
setup_first_admin.py
---------------------
Creates the first super_admin employee account.
Safe to run multiple times — skips if the email already exists.

Usage (from project root):
    python setup_first_admin.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from backend.database import create_employee, get_employee_by_email, migrate_central_schema


def main():
    print("=" * 50)
    print("  ManasBot — First Super Admin Setup")
    print("=" * 50)

    migrate_central_schema()

    name = input("\nFull name: ").strip()
    email = input("Email: ").strip().lower()
    password = input("Password: ").strip()

    if not name or not email or not password:
        print("\nERROR: All fields are required.")
        sys.exit(1)

    existing = get_employee_by_email(email)
    if existing:
        print(f"\nSkipped — an employee with email '{email}' already exists.")
        print(f"  Name: {existing['name']}, Role: {existing['role']}, Active: {existing['is_active']}")
        return

    emp = create_employee(name=name, email=email, plain_password=password, role="super_admin")
    print(f"\nSuper admin created successfully.")
    print(f"  ID:    {emp['id']}")
    print(f"  Name:  {emp['name']}")
    print(f"  Email: {emp['email']}")
    print(f"  Role:  {emp['role']}")
    print("\nYou can now log in at the admin panel with these credentials.")


if __name__ == "__main__":
    main()
