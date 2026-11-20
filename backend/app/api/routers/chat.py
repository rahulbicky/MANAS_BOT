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
from ...schemas.models import ChatRequest, ChatResponse, FeedbackRequest

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
        first_day_of_month = datetime.datetime.utcnow().replace(
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

        # 4. Knowledge documents
        docs = db.query(KnowledgeDocument.filename, KnowledgeDocument.content).filter(
            KnowledgeDocument.tenant_id == tenant_id,
            KnowledgeDocument.is_active == True
        ).all()
        doc_context = ""
        if docs:
            doc_context = "### UPLOADED KNOWLEDGE BASE DOCUMENTS:\n"
            curr_len = len(doc_context)
            max_chars = 8000
            for doc in docs:
                header = f"--- Document: {doc.filename} ---\n"
                content = doc.content or ""
                if curr_len + len(header) + len(content) > max_chars:
                    rem = max_chars - curr_len - len(header)
                    if rem > 100:
                        doc_context += header + content[:rem] + "... [truncated]\n\n"
                    break
                else:
                    doc_context += header + content + "\n\n"
                    curr_len = len(doc_context)

        return {
            "monthly_messages": monthly_messages,
            "company": company,
            "industry": industry,
            "desc": desc,
            "custom_prompt": custom_prompt,
            "faqs": faq_list,
            "doc_context": doc_context,
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
    4. Quota Gate Check
    5. Phase B: Async Groq Execution (adetect_intent, aget_answer with zero DB connections)
    6. Phase C: Fast DB Write (offloaded via run_in_threadpool, committed & closed immediately)
    7. Background Alerts & Notifications Dispatch
    """
    start_time = time.time()
    user_ip = request.client.host if request.client else None

    # ── 1. XSS sanitisation ────────────────────────────────────────────
    payload.question = html.escape(payload.question)

    # ── 2. Tenant lookup & validation ──────────────────────────────────
    current_tenant = get_tenant_by_id(payload.tenant_id)
    if not current_tenant:
        return ChatResponse(
            answer="Sorry, this chatbot is not properly configured. Please contact support.",
            intent="error_tenant_not_found",
            resolved=False,
        )

    # ── 3. Subscription expiry check ───────────────────────────────────
    end_date_str = current_tenant.get("subscription_end_date")
    if end_date_str:
        try:
            end_date = datetime.datetime.fromisoformat(end_date_str)
            if end_date < datetime.datetime.utcnow():
                return ChatResponse(
                    answer="Service temporarily unavailable",
                    intent="error_subscription_expired",
                    resolved=False,
                )
        except (ValueError, TypeError):
            pass

    # ── 4. Language gate check ─────────────────────────────────────────
    limits = get_tenant_limits(payload.tenant_id)
    if (
        payload.language != "en"
        and limits.get("languages") != "all"
        and payload.language not in limits.get("languages", ["en"])
    ):
        return ChatResponse(
            answer="Multi-language support is not available on your current plan. Please upgrade to Pro or Enterprise.",
            intent="error_feature_gated",
            resolved=False,
        )

    # ── 5. Phase A: Fast DB Read Context ───────────────────────────────
    try:
        context_data = await run_in_threadpool(_fetch_chat_read_context, payload.tenant_id)
    except Exception as e:
        logger.error(f"[chat router] Phase A context fetch failed for tenant {payload.tenant_id}: {e}")
        return ChatResponse(
            answer="Sorry, this chatbot is not properly configured. Please contact support.",
            intent="error_tenant_not_found",
            resolved=False,
        )

    # ── 6. Monthly quota check ─────────────────────────────────────────
    if context_data["monthly_messages"] >= limits.get("messages_per_month", 1000):
        return ChatResponse(
            answer="Monthly message quota reached for your current plan. Please upgrade to continue.",
            intent="error_quota_exceeded",
            resolved=False,
        )

    # ── 7. Phase B: Async Intent Detection (Zero DB Connections) ───────
    intent = await adetect_intent(
        payload.question,
        tenant_id=payload.tenant_id,
        company=context_data["company"],
        industry=context_data["industry"],
    )

    # ── 8. Lead Capture Detection ──────────────────────────────────────
    phone_match = re.search(r'\b(\d{10})\b', payload.question)
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', payload.question)
    words = payload.question.split()
    name_words = [
        w for w in words
        if not re.fullmatch(r'\d+', w) and '@' not in w and len(w) >= 2
    ]
    has_contact_info = bool(phone_match and email_match and name_words)

    if has_contact_info:
        phone_str = phone_match.group(1)
        email_str = email_match.group(0)
        name_str = " ".join(
            w for w in words
            if w != phone_str and w != email_str and w not in (",", ";", "-")
        ).strip()

        thank_you = "Thank you! Our support team has received your details and will contact you shortly."
        intent = "lead_captured"

        encrypted_q = encrypt_text(payload.question)
        encrypted_a = encrypt_text(thank_you)
        record_tokens(int((len(words) + len(thank_you.split())) * 1.3))

        notif_email = current_tenant.get("notification_email", "") if current_tenant else ""
        lead_data = {
            "name": name_str,
            "phone": phone_str,
            "email": email_str,
            "raw_message": payload.question,
            "is_notified": bool(notif_email),
        }

        # Phase C: Save turn
        response_time_ms = int((time.time() - start_time) * 1000)
        await run_in_threadpool(
            _save_chat_turn,
            tenant_id=payload.tenant_id,
            session_id=payload.session_id,
            encrypted_q=encrypted_q,
            encrypted_a=encrypted_a,
            intent=intent,
            page_url=payload.page_url,
            language=payload.language,
            is_resolved=True,
            response_time_ms=response_time_ms,
            user_ip=user_ip,
            lead_data=lead_data,
        )

        if notif_email:
            lead_info = f"Name: {name_str}\nPhone: {phone_str}\nEmail: {email_str}"
            background_tasks.add_task(
                send_lead_notification,
                client_email=notif_email,
                client_name=current_tenant.get("name", "Unknown"),
                lead_info=lead_info,
                inquiry=payload.question,
            )

        background_tasks.add_task(check_and_alert)
        return ChatResponse(answer=thank_you, intent=intent, resolved=True)

    # ── 9. Phase B: Async LLM Answer Generation (Zero DB Connections) ──
    # Match FAQs for this specific intent from pre-fetched list
    matching_faqs = [f for f in context_data["faqs"] if f["intent"] == intent]
    if matching_faqs:
        faq_context = "".join(f"Q: {f['question']}\nA: {f['answer']}\n\n" for f in matching_faqs)
    else:
        faq_context = "No specific FAQ found for this intent."

    answer = await aget_answer(
        question=payload.question,
        intent=intent,
        tenant_id=payload.tenant_id,
        language=payload.language,
        company=context_data["company"],
        industry=context_data["industry"],
        desc=context_data["desc"],
        custom_prompt=context_data["custom_prompt"],
        faq_context=faq_context,
        doc_context=context_data["doc_context"],
    )

    estimated_tokens = int(
        (len(payload.question.split()) + len(answer.split())) * 1.3
    )
    record_tokens(estimated_tokens)

    encrypted_q = encrypt_text(payload.question)
    encrypted_a = encrypt_text(answer)
    response_time_ms = int((time.time() - start_time) * 1000)

    # ── 10. Phase C: Fast DB Write (Short-lived Session) ───────────────
    await run_in_threadpool(
        _save_chat_turn,
        tenant_id=payload.tenant_id,
        session_id=payload.session_id,
        encrypted_q=encrypted_q,
        encrypted_a=encrypted_a,
        intent=intent,
        page_url=payload.page_url,
        language=payload.language,
        is_resolved=False,
        response_time_ms=response_time_ms,
        user_ip=user_ip,
        lead_data=None,
    )

    background_tasks.add_task(check_and_alert)

    return ChatResponse(answer=answer, intent=intent, resolved=False)


# ─────────────────────────────────────────────────────────────────────────────
# Secondary Endpoints (Offloaded to Worker Threadpool)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/chat/feedback")
@limiter.limit("5/minute")
async def chat_feedback_endpoint(
    request: Request,
    payload: FeedbackRequest
):
    """Receives end-of-chat feedback from the widget.

    Offloaded via run_in_threadpool to keep the event loop non-blocking.
    """
    def _record_feedback():
        db = None
        try:
            db = get_tenant_session(payload.tenant_id)
            existing = db.query(ChatFeedback).filter(
                ChatFeedback.tenant_id == payload.tenant_id,
                ChatFeedback.session_id == payload.session_id
            ).first()
            if existing:
                existing.rating = payload.rating
                existing.comment = payload.comment
            else:
                new_fb = ChatFeedback(
                    tenant_id=payload.tenant_id,
                    session_id=payload.session_id,
                    rating=payload.rating,
                    comment=payload.comment
                )
                db.add(new_fb)
            db.commit()
            return {"status": "success", "message": "Feedback recorded."}
        except Exception as e:
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
            logger.error(f"[chat feedback] Failed to record feedback for tenant {payload.tenant_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            if db:
                db.close()

    return await run_in_threadpool(_record_feedback)


@router.get("/chat/config")
@limiter.limit("20/minute")
async def chat_config_endpoint(
    request: Request,
    tenant_id: str
):
    """Public endpoint to fetch widget UI configuration (company name, logo, greeting).

    Offloaded via run_in_threadpool. Always returns 200 so widget never breaks.
    """
    def _fetch_config():
        _default = {
            "company_name": "MANAS BOT",
            "logo_url": "",
            "chatbot_greeting_message": "Hi! How can I help you today?",
            "brand_color_primary": "",
            "brand_color_secondary": ""
        }
        db = None
        try:
            db = get_tenant_session(tenant_id)
            profile = db.query(BusinessProfile).filter(BusinessProfile.tenant_id == tenant_id).first()
            if profile:
                return {
                    "company_name": profile.company_name or _default["company_name"],
                    "logo_url": profile.logo_url or "",
                    "chatbot_greeting_message": profile.chatbot_greeting_message or _default["chatbot_greeting_message"],
                    "brand_color_primary": profile.brand_color_primary or "",
                    "brand_color_secondary": profile.brand_color_secondary or ""
                }
            return _default
        except Exception as e:
            logger.warning(f"[chat config] Could not load config for tenant {tenant_id}: {e}")
            return _default
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    return await run_in_threadpool(_fetch_config)
