"""
app/core/security.py
--------------------
Two parallel auth systems:

  OLD (X-Auth-Token) — used by the existing client panel routes.
    "super-admin-secret"  → seller/super-admin bypass
    <api_key>             → per-tenant client auth

  NEW (Authorization: Bearer <jwt>) — used by employee-facing routes.
    JWT payload: {sub: employee_id, email, role, iat, exp}
    Validated by get_employee_from_token() / require_role().

Do not remove the old system until the client panel is fully migrated.
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


def get_tenant_db(
    request: Request,
    tenant_id: str = Query(..., description="The tenant/client ID"),
    x_auth_token: Optional[str] = Header(None, alias="X-Auth-Token"),
) -> Iterator[Session]:
    """Dependency that returns a session to the correct tenant's database.

    - Super-admin token ("super-admin-secret") bypasses per-tenant auth.
    - All other callers must supply the tenant's own API key.
    """
    if x_auth_token == "super-admin-secret":
        # Super-admin bypass — no tenant-level check needed
        pass
    else:
        if not x_auth_token:
            raise HTTPException(status_code=401, detail="Authentication token missing")

        tenant = get_tenant_by_id(tenant_id)
        if not tenant or tenant.get("api_key") != x_auth_token:
            raise HTTPException(
                status_code=403,
                detail="Invalid token or unauthorized for this tenant",
            )

        # Demo account read-only enforcement
        if tenant.get("is_demo_account") and request.method in ["POST", "PUT", "DELETE"]:
            # Allow chat endpoints since they need to POST messages
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
