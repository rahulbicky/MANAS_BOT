"""
api/routers/profile.py
-----------------------
Prefix: /admin
Routes:
  GET  /admin/profile — fetch business profile
  POST /admin/profile — create / update business profile
"""
import uuid
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..deps import get_tenant_db
from ....database import BusinessProfile
from ...schemas.models import BusinessProfileBase
from ...core.security import require_role

router = APIRouter(prefix="/admin", tags=["Profile"])


@router.get("/profile", response_model=BusinessProfileBase, dependencies=[Depends(require_role("super_admin", "admin", "support", "viewer"))])
async def get_profile(tenant_id: str = Query(...), db: Session = Depends(get_tenant_db)):
    profile = db.query(BusinessProfile).filter(BusinessProfile.tenant_id == tenant_id).first()
    if not profile:
        profile = BusinessProfile(id=str(uuid.uuid4()), tenant_id=tenant_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.post("/profile", response_model=BusinessProfileBase, dependencies=[Depends(require_role("super_admin", "admin"))])
async def update_profile(
    profile_data: BusinessProfileBase,
    tenant_id: str = Query(...),
    db: Session = Depends(get_tenant_db),
):
    profile = db.query(BusinessProfile).filter(BusinessProfile.tenant_id == tenant_id).first()
    if not profile:
        profile = BusinessProfile(id=str(uuid.uuid4()), tenant_id=tenant_id)
        db.add(profile)

    # FIX 2: Partial update — only overwrite fields that were explicitly provided in the request
    for field, value in profile_data.model_dump(exclude_none=True).items():
        if hasattr(profile, field):
            setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile
