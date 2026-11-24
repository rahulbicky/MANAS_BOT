"""
backend/app/repositories/chat_repo.py
-------------------------------------
Data access repository for chat logs, session memory, feedback, and leads.
Enforces short-lived database sessions and row-level tenant isolation.
"""
import datetime
import uuid
import logging
from typing import List, Dict, Optional, Any

from ...database import (
    get_tenant_session,
    ChatLog,
    Lead,
    ChatFeedback,
)
from ...encryption import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)


class ChatRepository:
    """Repository handling all persistence and retrieval of chat logs, history, and leads."""

    @staticmethod
    def count_monthly_messages(tenant_id: str) -> int:
        """Count total messages sent by a tenant in the current calendar month."""
        db = None
        try:
            db = get_tenant_session(tenant_id)
            first_day_of_month = datetime.datetime.now(datetime.timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            return (
                db.query(ChatLog.id)
                .filter(
                    ChatLog.tenant_id == tenant_id,
                    ChatLog.created_at >= first_day_of_month,
                )
                .count()
            )
        finally:
            if db:
                db.close()

    @staticmethod
    def get_recent_session_history(
        tenant_id: str, session_id: str, limit: int = 5
    ) -> List[Dict[str, str]]:
        """Retrieve and decrypt the last N turns for the given tenant and session.

        Returns chronological list of dicts: [{"question": str, "answer": str}, ...]
        """
        if not session_id or session_id == "unknown_session":
            return []

        db = None
        try:
            db = get_tenant_session(tenant_id)
            rows = (
                db.query(ChatLog.encrypted_question, ChatLog.encrypted_answer)
                .filter(
                    ChatLog.tenant_id == tenant_id,
                    ChatLog.session_id == session_id,
                )
                .order_by(ChatLog.created_at.desc())
                .limit(limit)
                .all()
            )

            history = []
            for enc_q, enc_a in reversed(rows):
                try:
                    q = decrypt_text(enc_q) if enc_q else ""
                except Exception:
                    q = enc_q or ""
                try:
                    a = decrypt_text(enc_a) if enc_a else ""
                except Exception:
                    a = enc_a or ""
                if q or a:
                    history.append({"question": q, "answer": a})

            return history
        except Exception as e:
            logger.warning(
                f"[chat_repo] Could not load session history for {tenant_id}/{session_id}: {e}"
            )
            return []
        finally:
            if db:
                db.close()

    @staticmethod
    def save_chat_turn(
        tenant_id: str,
        session_id: str,
        encrypted_q: str,
        encrypted_a: str,
        intent: str,
        page_url: str,
        language: str,
        is_resolved: bool,
        response_time_ms: int,
        user_ip: Optional[str] = None,
        lead_data: Optional[dict] = None,
    ) -> str:
        """Persist a single chat interaction and optional customer lead in a single atomic transaction."""
        db = None
        try:
            db = get_tenant_session(tenant_id)
            log_id = str(uuid.uuid4())
            new_log = ChatLog(
                id=log_id,
                tenant_id=tenant_id,
                session_id=session_id,
                encrypted_question=encrypted_q,
                encrypted_answer=encrypted_a,
                detected_intent=intent,
                page_url=page_url or "",
                language=language or "en",
                is_resolved=is_resolved,
                response_time_ms=response_time_ms,
                user_ip=user_ip or "",
            )
            db.add(new_log)

            if lead_data:
                lead_id = str(uuid.uuid4())
                new_lead = Lead(
                    id=lead_id,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    name=lead_data.get("name", ""),
                    phone=lead_data.get("phone", ""),
                    email=lead_data.get("email", ""),
                    raw_message=lead_data.get("raw_message", ""),
                    page_url=page_url or "",
                    is_notified=lead_data.get("is_notified", False),
                )
                db.add(new_lead)

            db.commit()
            return log_id
        finally:
            if db:
                db.close()

    @staticmethod
    def save_feedback(
        tenant_id: str, session_id: str, rating: int, comment: str = ""
    ) -> str:
        """Persist user feedback for a chat conversation."""
        db = None
        try:
            db = get_tenant_session(tenant_id)
            fb_id = str(uuid.uuid4())
            fb = ChatFeedback(
                id=fb_id,
                tenant_id=tenant_id,
                session_id=session_id,
                rating=rating,
                comment=comment or "",
            )
            db.add(fb)
            db.commit()
            return fb_id
        finally:
            if db:
                db.close()
