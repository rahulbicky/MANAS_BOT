"""
api/routers/chat.py
--------------------
Prefix: (none)
Routes:
  POST /chat          — main LLM endpoint used by the public-facing widget (fully decoupled async)
  POST /chat/feedback — feedback recording (offloaded to worker thread)
  GET  /chat/config   — widget UI config (offloaded to worker thread)
"""
import re
import html
import datetime
import time
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ...core.rate_limiter import limiter
from ....database import (
    get_tenant_session,
    get_tenant_by_id,
    get_tenant_limits,
    ChatLog,
    Lead,
    BusinessProfile,
    FAQ,
    KnowledgeDocument,
    ChatFeedback,
)
from ....encryption import encrypt_text
from ....email_notifier import send_lead_notification
from ....intent_chain import detect_intent, adetect_intent
from ....faq_chain import get_answer, aget_answer
from ....metrics_store import record_tokens
from ....alerting import check_and_alert
from ...schemas.models import ChatRequest, ChatResponse, FeedbackRequest, SourceCitation
from ....rag import aretrieve_relevant_chunks, format_rag_context
from ...services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


# ─────────────────────────────────────────────────────────────────────────────
# Synchronous Helper Functions for Phase A (Read) & Phase C (Write)
# Designed to run in worker threads via run_in_threadpool with short-lived sessions
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_chat_read_context(tenant_id: str) -> dict:
    """Phase A: Short-lived database read to retrieve quota status, business profile,

    active FAQs, and active knowledge documents.
    Closes the session immediately so zero DB connections are held during Groq calls.
    """
    db = None
    try:
        db = get_tenant_session(tenant_id)

        # 1. Monthly message quota count
        first_day_of_month = datetime.datetime.now(datetime.timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        monthly_messages = (
            db.query(ChatLog.id).filter(
                ChatLog.tenant_id == tenant_id,
                ChatLog.created_at >= first_day_of_month
            ).count()
        )

        # 2. Business profile
        try:
            with db.begin_nested():
                profile = db.query(
                    BusinessProfile.company_name,
                    BusinessProfile.industry,
                    BusinessProfile.business_description,
                    BusinessProfile.chatbot_system_prompt,
                ).filter(BusinessProfile.tenant_id == tenant_id).first()
        except Exception as profile_err:
            logger.warning(f"[chat router] Failed to load BusinessProfile for tenant {tenant_id}: {profile_err}")
            profile = None

        company = profile[0] if profile and profile[0] else "the company"
        industry = profile[1] if profile and profile[1] else "general services"
        desc = profile[2] if profile and profile[2] else ""
        custom_prompt = profile[3] if profile and profile[3] else ""

        # 3. Active FAQs
        faqs = db.query(FAQ.intent, FAQ.question, FAQ.answer).filter(
            FAQ.tenant_id == tenant_id,
            FAQ.is_active == True
        ).all()
        faq_list = [{"intent": f.intent, "question": f.question, "answer": f.answer} for f in faqs]

        return {
            "monthly_messages": monthly_messages,
            "company": company,
            "industry": industry,
            "desc": desc,
            "custom_prompt": custom_prompt,
            "faqs": faq_list,
        }
    finally:
        if db:
            db.close()


def _save_chat_turn(
    tenant_id: str,
    session_id: str,
    encrypted_q: str,
    encrypted_a: str,
    intent: str,
    page_url: str,
    language: str,
    is_resolved: bool,
    response_time_ms: int,
    user_ip: str,
    lead_data: dict = None,
) -> None:
    """Phase C: Short-lived database write to persist ChatLog and optionally Lead.

    Opens session, writes, commits, and closes immediately.
    """
    db = None
    try:
        db = get_tenant_session(tenant_id)
        new_log = ChatLog(
            tenant_id=tenant_id,
            session_id=session_id,
            encrypted_question=encrypted_q,
            encrypted_answer=encrypted_a,
            detected_intent=intent,
            page_url=page_url,
            language=language,
            is_resolved=is_resolved,
            response_time_ms=response_time_ms,
            user_ip=user_ip,
        )
        db.add(new_log)

        if lead_data:
            lead_record = Lead(
                tenant_id=tenant_id,
                session_id=session_id,
                name=lead_data["name"],
                phone=lead_data["phone"],
                email=lead_data["email"],
                raw_message=lead_data["raw_message"],
                page_url=page_url,
                is_notified=lead_data.get("is_notified", False),
            )
            db.add(lead_record)

        db.commit()
    except Exception as e:
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        logger.error(f"[chat router] Error saving chat turn for tenant {tenant_id}: {e}")
        raise
    finally:
        if db:
            db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Main Chat Endpoint (Decoupled 3-Phase Execution)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat_endpoint(
    request: Request,
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
):
    """Main conversational endpoint called by every chatbot widget.

    Architectural Pattern:
    1. Validation & Input Sanitization (XSS)
    2. Tenant Expiry & Language Gate Validation
    3. Phase A: Fast DB Read (offloaded via run_in_threadpool, DB closed immediately)
    4. Multi-Turn Session Memory Loading & Decryption
    5. Phase B: LangGraph Execution & AI Processing (zero DB connections held during LLM inference)
    6. Phase C: Fast DB Write (committed & closed immediately)
    7. Background Alerts & Notifications Dispatch
    """
    user_ip = request.client.host if request.client else None
    return await ChatService.process_chat(
        payload=payload,
        user_ip=user_ip,
        background_tasks=background_tasks,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Secondary Endpoints (Offloaded to Service Layer & Worker Threadpool)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/feedback")
@limiter.limit("5/minute")
async def chat_feedback_endpoint(
    request: Request,
    payload: FeedbackRequest
):
    """Receives end-of-chat feedback from the widget."""
    return await ChatService.record_feedback(
        tenant_id=payload.tenant_id,
        session_id=payload.session_id,
        rating=payload.rating,
        comment=payload.comment,
    )


@router.get("/chat/config")
@limiter.limit("20/minute")
async def chat_config_endpoint(
    request: Request,
    tenant_id: str
):
    """Public endpoint to fetch widget UI configuration (company name, logo, greeting)."""
    return await ChatService.get_widget_config(tenant_id=tenant_id)
