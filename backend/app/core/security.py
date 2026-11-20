"""
app/core/security.py
--------------------
Authentication and Authorization for ManasBot:

  1. Tenant API Key (X-Auth-Token: <api_key>)
     - Used by tenant/client panel routes and widget integrations.
     - Validated against the tenant's registered api_key.

  2. Employee JWT (Authorization: Bearer <jwt>)
     - Used by internal employees on developer/admin routes.
     - Validated by get_employee_from_token() and require_role().
"""
import datetime
from typing import Iterator, Optional

import jwt
from fastapi import Depends, HTTPException, Query, Header, Request
from sqlalchemy.orm import Session

from ...database import get_tenant_session, get_tenant_by_id, get_employee_by_id
from .config import JWT_SECRET, JWT_EXPIRE_HOURS


# ── Employee JWT helpers ─────────────────────────────────────────────────────

def create_employee_token(employee_id: str, email: str, role: str, role_changed_at: str = None) -> str:
    now = datetime.datetime.utcnow()
    payload = {
        "sub": employee_id,
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + datetime.timedelta(hours=JWT_EXPIRE_HOURS),
    }
    if role_changed_at:
        payload["role_changed_at"] = role_changed_at
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_employee_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# ── Employee auth dependencies ───────────────────────────────────────────────

async def get_employee_from_token(request: Request) -> dict:
    """FastAPI dependency — validates Bearer JWT and returns employee dict."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Employee authentication required.")
    token = auth_header[len("Bearer "):]
    payload = decode_employee_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    employee = get_employee_by_id(payload["sub"])
    if not employee or not employee.get("is_active"):
        raise HTTPException(status_code=401, detail="Employee account not found or deactivated.")

    # Option A: invalidate token if role was changed after it was issued
    role_changed_at = employee.get("role_changed_at")
    if role_changed_at:
        iat = payload.get("iat")
        if iat is not None:
            # PyJWT ≥2: iat is decoded as an int (Unix timestamp)
            if isinstance(iat, (int, float)):
                iat_dt = datetime.datetime.utcfromtimestamp(iat)
            else:
                iat_dt = iat  # already a datetime (older PyJWT)
            if isinstance(role_changed_at, str):
                role_changed_at = datetime.datetime.fromisoformat(role_changed_at)
            if role_changed_at > iat_dt:
                raise HTTPException(status_code=401, detail="Session invalidated. Please log in again.")

    return employee


def require_role(*allowed_roles: str):
    """Dependency factory — restricts a route to employees with one of the given roles."""
    async def _check(employee: dict = Depends(get_employee_from_token)) -> dict:
        if employee["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return employee
    return _check


def require_tenant_or_role(*allowed_roles: str):
    """Dependency factory for routes shared by both auth systems:
      - the tenant/client panel (X-Auth-Token = that tenant's own api_key) — full access
        to their own data, no role check (it's their data).
      - the employee/admin panel (Authorization: Bearer <jwt>) — access to any tenant's
        data, gated by role as usual.

    A request must satisfy ONE of the two, not both.
    """
    async def _check(
        request: Request,
        tenant_id: str = Query(..., description="The tenant/client ID"),
        x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
    ) -> dict:
        if x_auth_token:
            tenant = get_tenant_by_id(tenant_id)
            if tenant and tenant.get("api_key") == x_auth_token:
                return {"auth_type": "tenant", "tenant_id": tenant_id}
        employee = await get_employee_from_token(request)
        if employee["role"] not in allowed_roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return employee
    return _check


def get_tenant_db(
    request: Request,
    tenant_id: str = Query(..., description="The tenant/client ID"),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> Iterator[Session]:
    """Dependency that returns a session to the correct tenant's database.

    - Authenticates via either:
      1. Tenant API key (X-Auth-Token == tenant.api_key)
      2. Valid employee session (Authorization: Bearer <jwt>)
    - Demo accounts are enforced read-only for mutation requests.
    """
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail=f"Tenant '{tenant_id}' not found or is inactive.")

    is_authorized = False

    # 1. Check if caller provided valid tenant API key
    if x_auth_token and tenant.get("api_key") == x_auth_token:
        is_authorized = True
    else:
        # 2. Check if caller is an authenticated active employee via Bearer JWT
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            payload = decode_employee_token(token)
            if payload:
                employee = get_employee_by_id(payload.get("sub"))
                if employee and employee.get("is_active"):
                    is_authorized = True

    if not is_authorized:
        if not x_auth_token and not request.headers.get("Authorization"):
            raise HTTPException(status_code=401, detail="Authentication credentials missing.")
        raise HTTPException(
            status_code=403,
            detail="Invalid token or unauthorized for this tenant.",
        )

    # Demo account read-only enforcement
    if tenant.get("is_demo_account") and request.method in ["POST", "PUT", "DELETE", "PATCH"]:
        if not request.url.path.endswith("/chat"):
            raise HTTPException(status_code=403, detail="Action not permitted on demo accounts.")

    try:
        db = get_tenant_session(tenant_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        db.close()
