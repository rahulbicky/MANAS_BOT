"""
backend/app/services/chat_service.py
------------------------------------
Service layer orchestrating the decoupled 3-phase execution model for chat:
  Phase A: Database Read & Context Fetch (short-lived session via TenantRepository & ChatRepository)
  Phase B: LangGraph Execution & AI Processing (zero DB connections held during LLM inference)
  Phase C: Database Write & Async Dispatch (short-lived session for logs, leads, and alerts)

Enforces strict tenant isolation, quota management, and multi-turn history.
"""
import time
import html
import sys
import logging
import datetime
from typing import Optional, Dict, Any, List

from fastapi import BackgroundTasks
from starlette.concurrency import run_in_threadpool

from ..repositories.chat_repo import ChatRepository
from ..repositories.tenant_repo import TenantRepository
from ..schemas.models import ChatRequest, ChatResponse, SourceCitation
from ..core.config import HISTORY_WINDOW_TURNS
from ...encryption import encrypt_text
from ...metrics_store import record_tokens
from ...email_notifier import send_lead_notification
from ...alerting import check_and_alert
from ...rag.graph import ConversationState, run_chat_graph
from ..core.session_lock import session_lock, SessionLockTimeoutError
from ...database import ensure_utc, utc_now

logger = logging.getLogger(__name__)


def _get_chat_hook(name: str, fallback):
    """Retrieve runtime hook from chat router if available."""
    chat_mod = sys.modules.get("backend.app.api.routers.chat")
    if chat_mod and hasattr(chat_mod, name):
        return getattr(chat_mod, name)
    return fallback


class ChatService:
    """Enterprise service layer handling multi-tenant conversational AI lifecycle."""

    @staticmethod
    async def process_chat(
        payload: ChatRequest,
        user_ip: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> ChatResponse:
        """Main decoupled 3-phase conversational execution flow protected by session-level locking."""
        start_time = time.time()
        try:
            async with session_lock(payload.tenant_id, payload.session_id, timeout=10.0):
                return await ChatService._process_chat_inner(
                    payload=payload,
                    user_ip=user_ip,
                    background_tasks=background_tasks,
                    start_time=start_time,
                )
        except SessionLockTimeoutError:
            logger.warning(
                f"[chat_service] Session lock timeout for tenant={payload.tenant_id}, session={payload.session_id}"
            )
            return ChatResponse(
                answer="A message is already being processed for this conversation. Please wait a moment.",
                intent="error_session_busy",
                resolved=False,
                sources=[],
            )

    @staticmethod
    async def _process_chat_inner(
        payload: ChatRequest,
        user_ip: Optional[str] = None,
        background_tasks: Optional[BackgroundTasks] = None,
        start_time: float = 0.0,
    ) -> ChatResponse:
        # ── 1. Input Sanitization (XSS) ────────────────────────────────
        sanitized_question = html.escape(payload.question)

        # ── 2. Tenant Lookup & Validation ──────────────────────────────
        current_tenant = TenantRepository.get_tenant(payload.tenant_id)
        if not current_tenant:
            return ChatResponse(
                answer="Sorry, this chatbot is not properly configured. Please contact support.",
                intent="error_tenant_not_found",
                resolved=False,
                sources=[],
            )

        # ── 3. Subscription Expiry Check ───────────────────────────────
        end_date_str = current_tenant.get("subscription_end_date")
        if end_date_str:
            try:
                end_date = datetime.datetime.fromisoformat(end_date_str)
                if ensure_utc(end_date) < utc_now():
                    return ChatResponse(
                        answer="Service temporarily unavailable",
                        intent="error_subscription_expired",
                        resolved=False,
                        sources=[],
                    )
            except (ValueError, TypeError):
                pass

        # ── 4. Language Gate Check ─────────────────────────────────────
        limits = TenantRepository.get_limits(payload.tenant_id)
        allowed_languages = limits.get("languages", ["en"])
        if (
            payload.language != "en"
            and allowed_languages != "all"
            and payload.language not in allowed_languages
        ):
            return ChatResponse(
                answer="Multi-language support is not available on your current plan. Please upgrade to Pro or Enterprise.",
                intent="error_feature_gated",
                resolved=False,
                sources=[],
            )

        # ── 5. Phase A: Fast DB Read Context ───────────────────────────
        try:
            read_fn = _get_chat_hook(
                "_fetch_chat_read_context", TenantRepository.get_chat_read_context
            )
            context_data = await run_in_threadpool(read_fn, payload.tenant_id)
        except Exception as e:
            logger.error(
                f"[chat_service] Phase A context fetch failed for tenant {payload.tenant_id}: {e}"
            )
            return ChatResponse(
                answer="Sorry, this chatbot is not properly configured. Please contact support.",
                intent="error_tenant_not_found",
                resolved=False,
                sources=[],
            )

        # ── 6. Monthly Quota Check ─────────────────────────────────────
        max_messages = limits.get("messages_per_month", 1000)
        if context_data["monthly_messages"] >= max_messages:
            return ChatResponse(
                answer="Monthly message quota reached for your current plan. Please upgrade to continue.",
                intent="error_quota_exceeded",
                resolved=False,
                sources=[],
            )

        # ── 7. Multi-Turn Session History Retrieval ────────────────────
        chat_history = await run_in_threadpool(
            ChatRepository.get_recent_session_history,
            tenant_id=payload.tenant_id,
            session_id=payload.session_id,
            limit=HISTORY_WINDOW_TURNS,
        )

        # ── 8. Phase B: LangGraph Execution (Zero DB Connections Held) ──
        initial_state: ConversationState = {
            "question": sanitized_question,
            "session_id": payload.session_id,
            "tenant_id": payload.tenant_id,
            "language": payload.language,
            "page_url": payload.page_url,
            "chat_history": chat_history,
            "monthly_messages": context_data["monthly_messages"],
            "company": context_data["company"],
            "industry": context_data["industry"],
            "desc": context_data["desc"],
            "custom_prompt": context_data["custom_prompt"],
            "faqs": context_data["faqs"],
        }

        thread_id = f"{payload.tenant_id}:{payload.session_id}"
        graph_output = await run_chat_graph(initial_state, thread_id=thread_id)

        answer = graph_output.get("answer", "")
        intent = graph_output.get("intent", "information")
        is_resolved = graph_output.get("is_resolved", False)
        lead_data = graph_output.get("lead_data")
        raw_sources = graph_output.get("sources", [])

        sources = [
            SourceCitation(
                document_id=s.get("document_id", "") if isinstance(s, dict) else s.document_id,
                filename=s.get("filename", "") if isinstance(s, dict) else s.filename,
                relevance_score=s.get("relevance_score", 0.0) if isinstance(s, dict) else s.similarity_score,
            )
            for s in raw_sources
        ]

        # Record approximate token usage
        total_tokens = int((len(sanitized_question.split()) + len(answer.split())) * 1.3)
        record_tokens(total_tokens)

        # ── 9. Phase C: Fast DB Write (Short-lived Session) ─────────────
        encrypted_q = encrypt_text(sanitized_question)
        encrypted_a = encrypt_text(answer)
        response_time_ms = int((time.time() - start_time) * 1000)

        notif_email = current_tenant.get("notification_email", "") if current_tenant else ""
        if lead_data:
            lead_data["is_notified"] = bool(notif_email)

        save_fn = _get_chat_hook("_save_chat_turn", ChatRepository.save_chat_turn)
        await run_in_threadpool(
            save_fn,
            tenant_id=payload.tenant_id,
            session_id=payload.session_id,
            encrypted_q=encrypted_q,
            encrypted_a=encrypted_a,
            intent=intent,
            page_url=payload.page_url,
            language=payload.language,
            is_resolved=is_resolved,
            response_time_ms=response_time_ms,
            user_ip=user_ip,
            lead_data=lead_data,
        )

        # ── 10. Background Tasks Dispatch ──────────────────────────────
        if background_tasks:
            if lead_data and notif_email:
                lead_summary = (
                    f"Name: {lead_data.get('name', 'N/A')}\n"
                    f"Phone: {lead_data.get('phone', 'N/A')}\n"
                    f"Email: {lead_data.get('email', 'N/A')}"
                )
                background_tasks.add_task(
                    send_lead_notification,
                    client_email=notif_email,
                    client_name=current_tenant.get("name", "Unknown"),
                    lead_info=lead_summary,
                    inquiry=sanitized_question,
                )

            background_tasks.add_task(check_and_alert)

        return ChatResponse(
            answer=answer,
            intent=intent,
            resolved=is_resolved,
            sources=sources,
        )

    @staticmethod
    async def record_feedback(
        tenant_id: str,
        session_id: str,
        rating: int,
        comment: str = "",
    ) -> Dict[str, Any]:
        """Record user feedback for a chat conversation."""
        await run_in_threadpool(
            ChatRepository.save_feedback,
            tenant_id=tenant_id,
            session_id=session_id,
            rating=rating,
            comment=comment,
        )
        return {"status": "success", "message": "Feedback recorded."}

    @staticmethod
    async def get_widget_config(tenant_id: str) -> Dict[str, Any]:
        """Fetch widget display configuration for the tenant."""
        return await run_in_threadpool(TenantRepository.get_widget_config, tenant_id)
