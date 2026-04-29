"""
Session 1 test script — Employee CRUD operations.
Run from the project root: python test_employees.py
Safe to re-run; cleans up test data before each run.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import (
    _get_central_session, Employee, migrate_central_schema,
    create_employee, get_employee_by_email, get_employee_by_id,
    verify_employee_password, list_employees,
    deactivate_employee, update_employee_role,
)

TEST_EMAIL = "test_employee_session1@manasbot.test"
TEST_PASSWORD = "TestPass123!"


def _cleanup(email: str):
    session = _get_central_session()
    try:
        emp = session.query(Employee).filter(Employee.email == email).first()
        if emp:
            session.delete(emp)
            session.commit()
            print(f"[cleanup] removed existing test employee: {email}")
    finally:
        session.close()


def run():
    print("=" * 50)
    print("  Employee CRUD - Session 1 Tests")
    print("=" * 50)

    print("\n[setup] Running migrate_central_schema() to ensure employees table exists...")
    migrate_central_schema()
    print("[setup] Done.\n")

    _cleanup(TEST_EMAIL)

    # 1. Create
    print("\n1. create_employee()")
    emp = create_employee(
        name="Test Super Admin",
        email=TEST_EMAIL,
        plain_password=TEST_PASSWORD,
        role="super_admin",
    )
    assert emp["name"] == "Test Super Admin", "name mismatch"
    assert emp["email"] == TEST_EMAIL, "email mismatch"
    assert emp["role"] == "super_admin", "role mismatch"
    assert emp["is_active"] is True, "should be active"
    assert "id" in emp, "missing id"
    assert "password_hash" not in emp, "hash should not be in default dict"
    print(f"   OK  id={emp['id'][:8]}...")

    # 2. Duplicate email raises ValueError
    print("2. create_employee() with duplicate email raises ValueError")
    try:
        create_employee("Dup", TEST_EMAIL, "pass", "admin")
        assert False, "should have raised"
    except ValueError:
        print("   OK  ValueError raised as expected")

    # 3. Invalid role raises ValueError
    print("3. create_employee() with invalid role raises ValueError")
    try:
        create_employee("Bad", "other@test.com", "pass", "god_mode")
        assert False, "should have raised"
    except ValueError:
        print("   OK  ValueError raised as expected")

    # 4. Fetch by email (includes hash)
    print("4. get_employee_by_email()")
    fetched = get_employee_by_email(TEST_EMAIL)
    assert fetched is not None, "should find employee"
    assert fetched["email"] == TEST_EMAIL
    assert "password_hash" in fetched, "hash must be present for login use"
    print(f"   OK  name={fetched['name']}")

    # 5. Fetch by id (no hash)
    print("5. get_employee_by_id()")
    by_id = get_employee_by_id(emp["id"])
    assert by_id is not None
    assert by_id["id"] == emp["id"]
    assert "password_hash" not in by_id, "hash must not be exposed by id lookup"
    print("   OK")

    # 6. Verify correct password
    print("6. verify_employee_password() — correct")
    assert verify_employee_password(fetched, TEST_PASSWORD) is True
    print("   OK")

    # 7. Verify wrong password
    print("7. verify_employee_password() — wrong")
    assert verify_employee_password(fetched, "WrongPassword!") is False
    print("   OK")

    # 8. List employees
    print("8. list_employees()")
    all_emps = list_employees()
    assert len(all_emps) >= 1
    ids = [e["id"] for e in all_emps]
    assert emp["id"] in ids
    print(f"   OK  total={len(all_emps)}")

    # 9. Update role
    print("9. update_employee_role() super_admin -> admin")
    updated = update_employee_role(emp["id"], "admin")
    assert updated is not None
    assert updated["role"] == "admin"
    print("   OK")

    # 10. update_employee_role() with invalid role
    print("10. update_employee_role() with invalid role")
    try:
        update_employee_role(emp["id"], "overlord")
        assert False, "should have raised"
    except ValueError:
        print("    OK  ValueError raised")

    # 11. Deactivate
    print("11. deactivate_employee()")
    deactivated = deactivate_employee(emp["id"])
    assert deactivated is not None
    assert deactivated["is_active"] is False
    print("    OK")

    # 12. Verify deactivation persists in DB
    print("12. verify deactivation persists")
    refetched = get_employee_by_email(TEST_EMAIL)
    assert refetched is not None
    assert refetched["is_active"] is False
    print("    OK")

    # 13. Deactivate non-existent employee returns None
    print("13. deactivate_employee() on unknown id returns None")
    result = deactivate_employee("00000000-0000-0000-0000-000000000000")
    assert result is None
    print("    OK")

    _cleanup(TEST_EMAIL)

    print("\n" + "=" * 50)
    print("  All 13 checks passed.")
    print("=" * 50)


if __name__ == "__main__":
    run()
