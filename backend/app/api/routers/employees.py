"""
api/routers/employees.py
-------------------------
Prefix: /admin
Routes:
  POST   /admin/employees                    — create employee (super_admin only)
  GET    /admin/employees                    — list employees (super_admin only)
  PATCH  /admin/employees/{id}/deactivate    — deactivate employee (super_admin only)
  PATCH  /admin/employees/{id}/role          — update employee role (super_admin only)
"""
from fastapi import APIRouter, Depends, HTTPException

from ...core.security import require_role
from ....database import create_employee, list_employees, deactivate_employee, update_employee_role
from ...schemas.models import EmployeeCreateRequest, EmployeeRoleUpdateRequest

router = APIRouter(prefix="/admin", tags=["Employees"])


@router.post("/employees", dependencies=[Depends(require_role("super_admin"))])
async def create_employee_endpoint(payload: EmployeeCreateRequest):
    try:
        return create_employee(payload.name, payload.email, payload.password, payload.role)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/employees", dependencies=[Depends(require_role("super_admin"))])
async def list_employees_endpoint():
    return list_employees()


@router.patch("/employees/{employee_id}/deactivate", dependencies=[Depends(require_role("super_admin"))])
async def deactivate_employee_endpoint(employee_id: str):
    emp = deactivate_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return emp


@router.patch("/employees/{employee_id}/role", dependencies=[Depends(require_role("super_admin"))])
async def update_employee_role_endpoint(employee_id: str, payload: EmployeeRoleUpdateRequest):
    try:
        emp = update_employee_role(employee_id, payload.role)
        if not emp:
            raise HTTPException(status_code=404, detail="Employee not found.")
        return emp
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
