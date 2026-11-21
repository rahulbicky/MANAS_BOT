"""
api/routers/leads.py
---------------------
Prefix: /admin
Routes:
  GET /admin/leads  — all captured leads for this tenant
  GET /admin/chats  — all chat logs (decrypted) for this tenant
"""
from typing import List

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from collections import defaultdict

from ..deps import get_tenant_db
from ....database import Lead, ChatLog, ChatFeedback
from ....encryption import decrypt_text
from ...schemas.models import ChatLogResponse
from ...utils.formatters import format_utc
from ...core.security import require_tenant_or_role

router = APIRouter(prefix="/admin", tags=["Leads"])


@router.get("/leads", dependencies=[Depends(require_tenant_or_role("super_admin", "admin", "support"))])
async def get_leads(
    tenant_id: str = Query(...),
    limit: int = Query(200, ge=1, le=1000, description="Max leads to return (default: 200, max: 1000)"),
    offset: int = Query(0, ge=0, description="Offset for pagination (default: 0)"),
    db: Session = Depends(get_tenant_db),
):
    leads = (
        db.query(Lead)
        .filter(Lead.tenant_id == tenant_id)
        .order_by(Lead.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": lead.id,
            "session_id": lead.session_id,
            "name": lead.name,
            "phone": lead.phone,
            "email": lead.email,
            "raw_message": lead.raw_message,
            "page_url": lead.page_url,
            "is_notified": lead.is_notified,
            "created_at": format_utc(lead.created_at),
        }
        for lead in leads
    ]


@router.get("/chats", response_model=List[ChatLogResponse], dependencies=[Depends(require_tenant_or_role("super_admin", "admin", "support", "viewer"))])
async def get_all_chats(
    tenant_id: str = Query(...),
    limit: int = Query(200, ge=1, le=1000, description="Max chat logs to return (default: 200, max: 1000)"),
    offset: int = Query(0, ge=0, description="Offset for pagination (default: 0)"),
    db: Session = Depends(get_tenant_db),
):
    # Fetch paginated slice of chat logs, newest first
    logs = (
        db.query(ChatLog)
        .filter(ChatLog.tenant_id == tenant_id)
        .order_by(ChatLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    if not logs:
        return []

    # Fetch feedbacks only for sessions in the current slice
    session_ids = list({log.session_id for log in logs if log.session_id})
    fb_dict = {}
    if session_ids:
        feedbacks = (
            db.query(ChatFeedback)
            .filter(ChatFeedback.tenant_id == tenant_id, ChatFeedback.session_id.in_(session_ids))
            .all()
        )
        fb_dict = {f.session_id: f for f in feedbacks}

    # Calculate session duration only for the fetched sessions
    session_durations = {}
    if session_ids:
        times_rows = (
            db.query(ChatLog.session_id, ChatLog.created_at)
            .filter(ChatLog.tenant_id == tenant_id, ChatLog.session_id.in_(session_ids))
            .all()
        )
        session_times = defaultdict(list)
        for sid, c_at in times_rows:
            if sid and c_at:
                session_times[sid].append(c_at)
        for sid, times in session_times.items():
            if times:
                delta = max(times) - min(times)
                session_durations[sid] = int(delta.total_seconds())

    results = []
    for log in logs:
        try:
            decrypted_q = decrypt_text(log.encrypted_question) if log.encrypted_question else ""
        except Exception:
            decrypted_q = log.encrypted_question or ""

        try:
            decrypted_a = decrypt_text(log.encrypted_answer) if log.encrypted_answer else ""
        except Exception:
            decrypted_a = log.encrypted_answer or ""

        fb = fb_dict.get(log.session_id)
        results.append(
            {
                "id": log.id,
                "session_id": log.session_id if log.session_id else "unknown_session",
                "question": decrypted_q,
                "answer": decrypted_a,
                "intent": log.detected_intent or "information",
                "page_url": log.page_url or "",
                "is_resolved": bool(log.is_resolved) if log.is_resolved is not None else True,
                "language": log.language or "en",
                "created_at": format_utc(log.created_at),
                "response_time_ms": getattr(log, "response_time_ms", 0) or 0,
                "feedback_rating": fb.rating if fb else None,
                "feedback_comment": fb.comment if fb else None,
                "feedback_created_at": format_utc(fb.created_at) if fb else None,
                "duration_seconds": session_durations.get(log.session_id)
            }
        )
    return results


@router.get("/feedback/stats", dependencies=[Depends(require_tenant_or_role("super_admin", "admin", "support", "viewer"))])
async def get_feedback_stats(tenant_id: str = Query(...), db: Session = Depends(get_tenant_db)):
    feedbacks = db.query(ChatFeedback).filter(ChatFeedback.tenant_id == tenant_id).all()
    if not feedbacks:
        return {"average": 0, "count": 0}
    avg = sum(f.rating for f in feedbacks) / len(feedbacks)
    return {"average": round(avg, 1), "count": len(feedbacks)}
