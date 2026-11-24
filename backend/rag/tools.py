"""
backend/rag/tools.py
--------------------
Agentic AI Tools for ManasBot.

Provides safe, tenant-isolated tools for LangChain and LangGraph agentic workflows:
  1. KnowledgeRetrievalTool: Semantic retrieval over tenant vector knowledge base
  2. BusinessProfileTool: Retrieves tenant business profile & customer service hours
  3. LeadCaptureTool: Structured contact & inquiry persistence
  4. SupportIncidentTool: Escalates and logs client support/operational incidents

All tools enforce:
  - Strict Pydantic input schemas
  - Multi-tenant data isolation (no cross-tenant leakage)
  - Execution timeout boundaries
  - Resilient error handling (never crashes host process)
  - Structured audit logging with execution timing
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from langchain_core.tools import StructuredTool

from ..app.core.config import CHAT_TOP_K, CHAT_SIMILARITY_THRESHOLD
from ..database import get_tenant_session, BusinessProfile, Lead, Incident
from .retriever import aretrieve_relevant_chunks, RetrievedChunk

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pydantic Schemas for Tools
# ─────────────────────────────────────────────────────────────────────────────

class ToolExecutionResult(BaseModel):
    """Standardized result returned by agent tool execution."""
    success: bool
    tool_name: str
    tenant_id: str
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: float = 0.0


class KnowledgeRetrievalInput(BaseModel):
    """Input parameters for tenant knowledge base retrieval."""
    tenant_id: str = Field(..., description="Unique tenant identifier for data isolation")
    query: str = Field(..., min_length=2, max_length=1000, description="Semantic search query")
    top_k: int = Field(default=CHAT_TOP_K, ge=1, le=10, description="Max candidate chunks to return")


class BusinessProfileInput(BaseModel):
    """Input parameters for querying business profile."""
    tenant_id: str = Field(..., description="Unique tenant identifier for data isolation")


class LeadCaptureInput(BaseModel):
    """Input parameters for capturing customer lead details."""
    tenant_id: str = Field(..., description="Unique tenant identifier for data isolation")
    name: str = Field(..., min_length=1, max_length=150, description="Customer full name")
    phone: Optional[str] = Field(default="", max_length=40, description="Customer contact phone number")
    email: Optional[str] = Field(default="", max_length=150, description="Customer email address")
    raw_message: str = Field(..., min_length=1, max_length=2000, description="Customer inquiry or message")
    session_id: Optional[str] = Field(default="", max_length=100, description="Active chat session identifier")


class SupportIncidentInput(BaseModel):
    """Input parameters for logging a support or technical incident."""
    tenant_id: str = Field(..., description="Unique tenant identifier for data isolation")
    title: str = Field(..., min_length=3, max_length=200, description="Summary title of the incident")
    description: str = Field(..., min_length=5, max_length=3000, description="Detailed incident description")
    category: str = Field(default="general", max_length=50, description="Incident category (e.g., billing, service, tech)")
    severity: str = Field(default="medium", max_length=20, description="Severity: low, medium, high, critical")


# ─────────────────────────────────────────────────────────────────────────────
# Core Tool Execution Implementations
# ─────────────────────────────────────────────────────────────────────────────

async def execute_knowledge_retrieval(
    tenant_id: str,
    query: str,
    top_k: int = CHAT_TOP_K,
    timeout_seconds: float = 8.0,
) -> ToolExecutionResult:
    """Executes semantic RAG vector retrieval within tenant boundaries."""
    start_t = time.perf_counter()
    try:
        chunks: List[RetrievedChunk] = await asyncio.wait_for(
            aretrieve_relevant_chunks(
                tenant_id=tenant_id,
                query=query,
                top_k=top_k,
                threshold=CHAT_SIMILARITY_THRESHOLD,
            ),
            timeout=timeout_seconds,
        )
        latency = (time.perf_counter() - start_t) * 1000
        formatted_chunks = [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "filename": c.filename,
                "content": c.chunk_text,
                "similarity_score": round(c.similarity_score, 4),
            }
            for c in chunks
        ]
        logger.info(
            f"[AgentTool:KnowledgeRetrieval] tenant={tenant_id} query='{query[:30]}...' "
            f"found={len(formatted_chunks)} latency={latency:.2f}ms"
        )
        return ToolExecutionResult(
            success=True,
            tool_name="KnowledgeRetrievalTool",
            tenant_id=tenant_id,
            data={"chunks": formatted_chunks, "count": len(formatted_chunks)},
            latency_ms=latency,
        )
    except asyncio.TimeoutError:
        latency = (time.perf_counter() - start_t) * 1000
        logger.warning(f"[AgentTool:KnowledgeRetrieval] Timeout ({timeout_seconds}s) for tenant={tenant_id}")
        return ToolExecutionResult(
            success=False,
            tool_name="KnowledgeRetrievalTool",
            tenant_id=tenant_id,
            error=f"Retrieval timed out after {timeout_seconds}s",
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.perf_counter() - start_t) * 1000
        logger.error(f"[AgentTool:KnowledgeRetrieval] Error for tenant={tenant_id}: {exc}")
        return ToolExecutionResult(
            success=False,
            tool_name="KnowledgeRetrievalTool",
            tenant_id=tenant_id,
            error=str(exc),
            latency_ms=latency,
        )


async def execute_business_profile(
    tenant_id: str,
    timeout_seconds: float = 5.0,
) -> ToolExecutionResult:
    """Retrieves business profile and hours for the tenant without holding long DB sessions."""
    start_t = time.perf_counter()

    def _sync_fetch():
        session = get_tenant_session(tenant_id)
        try:
            profile = session.query(BusinessProfile).filter_by(tenant_id=tenant_id).first()
            if not profile:
                return None
            return {
                "company_name": profile.company_name or "",
                "industry": profile.industry or "",
                "business_description": profile.business_description or "",
                "website": profile.website or "",
                "support_email": profile.support_email or "",
                "phone": profile.phone or "",
                "business_hours": profile.business_hours or "",
                "address": f"{profile.address_street}, {profile.city}, {profile.state} {profile.zip_code}".strip(", "),
            }
        finally:
            session.close()

    try:
        profile_data = await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch),
            timeout=timeout_seconds,
        )
        latency = (time.perf_counter() - start_t) * 1000
        return ToolExecutionResult(
            success=True,
            tool_name="BusinessProfileTool",
            tenant_id=tenant_id,
            data=profile_data or {"message": "No custom business profile configured."},
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.perf_counter() - start_t) * 1000
        logger.error(f"[AgentTool:BusinessProfile] Error for tenant={tenant_id}: {exc}")
        return ToolExecutionResult(
            success=False,
            tool_name="BusinessProfileTool",
            tenant_id=tenant_id,
            error=str(exc),
            latency_ms=latency,
        )


async def execute_lead_capture(
    tenant_id: str,
    name: str,
    raw_message: str,
    phone: str = "",
    email: str = "",
    session_id: str = "",
    timeout_seconds: float = 5.0,
) -> ToolExecutionResult:
    """Persists customer contact information for sales/support outreach."""
    start_t = time.perf_counter()

    def _sync_insert():
        session = get_tenant_session(tenant_id)
        try:
            lead = Lead(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                session_id=session_id or str(uuid.uuid4()),
                name=name.strip(),
                phone=phone.strip(),
                email=email.strip(),
                raw_message=raw_message.strip(),
                is_notified=False,
            )
            session.add(lead)
            session.commit()
            return {"lead_id": lead.id, "name": lead.name, "created": True}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        result_data = await asyncio.wait_for(
            asyncio.to_thread(_sync_insert),
            timeout=timeout_seconds,
        )
        latency = (time.perf_counter() - start_t) * 1000
        logger.info(f"[AgentTool:LeadCapture] Saved lead id={result_data['lead_id']} tenant={tenant_id}")
        return ToolExecutionResult(
            success=True,
            tool_name="LeadCaptureTool",
            tenant_id=tenant_id,
            data=result_data,
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.perf_counter() - start_t) * 1000
        logger.error(f"[AgentTool:LeadCapture] Failed for tenant={tenant_id}: {exc}")
        return ToolExecutionResult(
            success=False,
            tool_name="LeadCaptureTool",
            tenant_id=tenant_id,
            error=str(exc),
            latency_ms=latency,
        )


async def execute_support_incident(
    tenant_id: str,
    title: str,
    description: str,
    category: str = "general",
    severity: str = "medium",
    timeout_seconds: float = 5.0,
) -> ToolExecutionResult:
    """Logs an operational incident or escalated support ticket."""
    start_t = time.perf_counter()

    def _sync_insert():
        session = get_tenant_session(tenant_id)
        try:
            incident = Incident(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                title=title.strip(),
                description=description.strip(),
                category=category.strip().lower(),
                severity=severity.strip().lower(),
                status="open",
                client_read=False,
            )
            session.add(incident)
            session.commit()
            return {
                "incident_id": incident.id,
                "title": incident.title,
                "severity": incident.severity,
                "status": incident.status,
            }
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    try:
        result_data = await asyncio.wait_for(
            asyncio.to_thread(_sync_insert),
            timeout=timeout_seconds,
        )
        latency = (time.perf_counter() - start_t) * 1000
        logger.info(f"[AgentTool:SupportIncident] Created incident id={result_data['incident_id']} tenant={tenant_id}")
        return ToolExecutionResult(
            success=True,
            tool_name="SupportIncidentTool",
            tenant_id=tenant_id,
            data=result_data,
            latency_ms=latency,
        )
    except Exception as exc:
        latency = (time.perf_counter() - start_t) * 1000
        logger.error(f"[AgentTool:SupportIncident] Failed for tenant={tenant_id}: {exc}")
        return ToolExecutionResult(
            success=False,
            tool_name="SupportIncidentTool",
            tenant_id=tenant_id,
            error=str(exc),
            latency_ms=latency,
        )


# ─────────────────────────────────────────────────────────────────────────────
# LangChain Structured Tool Factory (Scoped to Tenant)
# ─────────────────────────────────────────────────────────────────────────────

def get_tenant_agent_tools(tenant_id: str) -> List[StructuredTool]:
    """Generates LangChain StructuredTools pre-bound to a specific tenant_id.

    This guarantees that agent calls can never accidentally access or mutate
    data belonging to another tenant.
    """
    async def _retrieval_coro(query: str, top_k: int = CHAT_TOP_K) -> Dict[str, Any]:
        res = await execute_knowledge_retrieval(tenant_id=tenant_id, query=query, top_k=top_k)
        return res.model_dump()

    async def _profile_coro() -> Dict[str, Any]:
        res = await execute_business_profile(tenant_id=tenant_id)
        return res.model_dump()

    async def _lead_coro(name: str, raw_message: str, phone: str = "", email: str = "") -> Dict[str, Any]:
        res = await execute_lead_capture(
            tenant_id=tenant_id,
            name=name,
            raw_message=raw_message,
            phone=phone,
            email=email,
        )
        return res.model_dump()

    async def _incident_coro(title: str, description: str, category: str = "general", severity: str = "medium") -> Dict[str, Any]:
        res = await execute_support_incident(
            tenant_id=tenant_id,
            title=title,
            description=description,
            category=category,
            severity=severity,
        )
        return res.model_dump()

    class _TenantQueryInput(BaseModel):
        query: str = Field(..., description="The query to search in knowledge base")
        top_k: int = Field(default=CHAT_TOP_K, description="Number of chunks")

    class _TenantProfileInput(BaseModel):
        pass

    class _TenantLeadInput(BaseModel):
        name: str = Field(..., description="Lead contact name")
        raw_message: str = Field(..., description="Message or inquiry text")
        phone: str = Field(default="", description="Phone number")
        email: str = Field(default="", description="Email address")

    class _TenantIncidentInput(BaseModel):
        title: str = Field(..., description="Incident title")
        description: str = Field(..., description="Incident details")
        category: str = Field(default="general", description="Category")
        severity: str = Field(default="medium", description="Severity level")

    return [
        StructuredTool.from_function(
            name="knowledge_retrieval",
            description="Searches tenant-verified knowledge base documents for relevant answers.",
            coroutine=_retrieval_coro,
            args_schema=_TenantQueryInput,
        ),
        StructuredTool.from_function(
            name="business_profile",
            description="Retrieves company contact details, address, hours, and description.",
            coroutine=_profile_coro,
            args_schema=_TenantProfileInput,
        ),
        StructuredTool.from_function(
            name="lead_capture",
            description="Stores contact details of interested prospective leads.",
            coroutine=_lead_coro,
            args_schema=_TenantLeadInput,
        ),
        StructuredTool.from_function(
            name="support_incident",
            description="Creates an operational support ticket or records an issue.",
            coroutine=_incident_coro,
            args_schema=_TenantIncidentInput,
        ),
    ]
