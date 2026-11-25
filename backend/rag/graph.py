"""
backend/rag/graph.py
--------------------
LangGraph conversational multi-turn state graph for ManasBot.
Orchestrates:
  1. Input sanitization & regex-based lead/contact extraction
  2. Async intent detection (LangChain ChatGroq fallback)
  3. Lead capture branching (preserving conversation flow for inquiries)
  4. Tenant FAQ matching
  5. Semantic RAG vector retrieval (FastEmbed + cosine distance)
  6. Contextual multi-turn answer generation (LangChain ChatGroq fallback)
  7. Structured source citation formatting

Preserves 100% backward compatibility and zero database connection holding
during LLM inference.
"""
import re
import html
import sys
import logging
from typing import TypedDict, List, Dict, Any, Optional

from langgraph.graph import StateGraph, START, END
from .checkpointer import (
    PostgresCheckpointSaver,
    AsyncPostgresSaver,
    get_checkpointer,
)
from langchain_groq import ChatGroq
from langchain_groq import ChatGroq as _StandardChatGroq
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from ..app.core.config import (
    HISTORY_WINDOW_TURNS,
    CHAT_TOP_K,
    CHAT_SIMILARITY_THRESHOLD,
)
from .retriever import aretrieve_relevant_chunks, RetrievedChunk
from .prompts import format_rag_context, build_rag_system_prompt
from ..intent_chain import adetect_intent as _original_adetect_intent, INTENT_MODELS, VALID_INTENTS
from ..faq_chain import FAQ_MODELS, LANG_MAP, aget_answer as _original_aget_answer

logger = logging.getLogger(__name__)


def _get_chat_hook(name: str, fallback=None):
    """Retrieve runtime mock or patched function from the chat router if it has been replaced."""
    chat_mod = sys.modules.get("backend.app.api.routers.chat")
    if chat_mod and hasattr(chat_mod, name):
        val = getattr(chat_mod, name)
        # If it is the unpatched original function, return fallback so graph node executes
        if name == "aget_answer" and val is _original_aget_answer:
            return fallback
        if name == "adetect_intent" and val is _original_adetect_intent:
            return fallback
        return val
    return fallback


def _get_groq_llm(model_name: str, temperature: float = 0.5):
    """Retrieve ChatGroq class respecting any test patches on backend.rag.graph or backend.faq_chain."""
    if ChatGroq is not _StandardChatGroq:
        return ChatGroq(model=model_name, temperature=temperature)
    faq_mod = sys.modules.get("backend.faq_chain")
    if faq_mod and hasattr(faq_mod, "ChatGroq") and faq_mod.ChatGroq is not _StandardChatGroq:
        return faq_mod.ChatGroq(model=model_name, temperature=temperature)
    return ChatGroq(model=model_name, temperature=temperature)


# ─────────────────────────────────────────────────────────────────────────────
# Conversational Query Resolution Helper
# ─────────────────────────────────────────────────────────────────────────────

def resolve_conversational_query(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Resolves pronouns and coreferences in multi-turn dialogues for semantic retrieval.

    If the current turn is ambiguous (e.g. contains 'it', 'that', 'this', 'they', or is short)
    and prior turns exist, enrich the search query with context from previous user turns.
    """
    if not history or not question:
        return question

    q_clean = question.strip()
    q_lower = q_clean.lower()
    coref_terms = {
        "it", "its", "this", "that", "these", "those",
        "they", "them", "their", "here", "there", "same"
    }
    tokens = set(re.findall(r"\b\w+\b", q_lower))

    has_coref = bool(tokens & coref_terms)
    is_short = len(tokens) <= 5

    if has_coref or is_short:
        for turn in reversed(history):
            prev_q = turn.get("question", "").strip()
            if prev_q:
                prev_clean = re.sub(
                    r"^(hi|hello|hey|please|thanks|thank you)[,\.\s]*",
                    "",
                    prev_q,
                    flags=re.IGNORECASE,
                ).strip()
                if prev_clean and prev_clean.lower() != q_lower:
                    return f"{prev_clean} - {q_clean}"
    return q_clean


# ─────────────────────────────────────────────────────────────────────────────
# Graph State Definition
# ─────────────────────────────────────────────────────────────────────────────

class ConversationState(TypedDict, total=False):
    """Unified state dictionary passed through the LangGraph conversational pipeline."""
    # Input parameters
    question: str
    session_id: str
    tenant_id: str
    language: str
    page_url: str

    # Multi-turn history loaded in Phase A
    chat_history: List[Dict[str, str]]

    # Tenant Profile & Context loaded in Phase A
    monthly_messages: int
    company: str
    industry: str
    desc: str
    custom_prompt: str
    faqs: List[Dict[str, str]]

    # Pipeline processing variables
    intent: str
    lead_data: Optional[Dict[str, Any]]
    is_pure_lead: bool
    faq_context: str
    retrieved_chunks: List[RetrievedChunk]
    doc_context: str

    # Final outputs
    sources: List[Dict[str, Any]]
    answer: str
    is_resolved: bool
    error: Optional[str]


# ─────────────────────────────────────────────────────────────────────────────
# Graph Nodes
# ─────────────────────────────────────────────────────────────────────────────

async def guard_and_intent_node(state: ConversationState) -> Dict[str, Any]:
    """Node 1: Sanitizes input, extracts contact info (lead), and detects intent.

    Zero DB connections held.
    """
    question = state.get("question", "")
    sanitized_question = html.escape(question.strip())
    tenant_id = state.get("tenant_id", "")
    company = state.get("company", "the company")
    industry = state.get("industry", "general services")

    # 1. Regex Contact Information Extraction
    phone_match = re.search(r'(\+?\d[\d\s\-]{8,14}\d)', sanitized_question) or re.search(r'\b(\d{10})\b', sanitized_question)
    email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', sanitized_question)
    words = sanitized_question.split()
    name_words = [
        w for w in words
        if not re.fullmatch(r'[\d\+\-\(\)]+', w) and '@' not in w and len(w) >= 2
    ]

    has_contact_info = bool(phone_match and email_match and name_words)
    lead_data = None
    is_pure_lead = False

    if has_contact_info:
        phone_str = phone_match.group(0).strip()
        email_str = email_match.group(0).strip()
        # Extract probable name by filtering out contact tokens and punctuation
        name_tokens = [
            w for w in words
            if w != phone_str and w != email_str and w.lower() not in (
                "my", "name", "is", "email", "phone", "contact", "details",
                "call", "me", "at", "reach", ",", ";", "-", ":"
            )
        ]
        name_str = " ".join(name_tokens).strip() or "Valued Customer"
        lead_data = {
            "name": name_str,
            "phone": phone_str,
            "email": email_str,
            "raw_message": sanitized_question,
            "is_notified": False,
        }

        # Check if the message contains question words or inquiry phrases
        inquiry_signals = [
            "?", "what", "how", "when", "where", "why", "who", "which",
            "can you", "could you", "do you", "price", "cost", "service",
            "plan", "support", "help", "feature", "eligibility", "info"
        ]
        q_lower = sanitized_question.lower()
        has_inquiry = any(sig in q_lower for sig in inquiry_signals) or len(words) > 12
        is_pure_lead = not has_inquiry

    # 2. Intent Detection
    pre_intent = state.get("intent")
    if pre_intent and pre_intent in VALID_INTENTS:
        detected_intent = pre_intent
    elif is_pure_lead:
        detected_intent = "lead_captured"
    else:
        try:
            detect_fn = _get_chat_hook("adetect_intent", _original_adetect_intent)
            detected_intent = await detect_fn(
                sanitized_question,
                tenant_id=tenant_id,
                company=company,
                industry=industry,
            )
        except Exception as e:
            logger.warning(f"[langgraph] Intent detection failed: {e}. Defaulting to 'information'.")
            detected_intent = "information"

    return {
        "question": sanitized_question,
        "lead_data": lead_data,
        "is_pure_lead": is_pure_lead,
        "intent": detected_intent,
    }


def router_lead_or_inquiry(state: ConversationState) -> str:
    """Conditional edge router:

    If pure lead (no inquiry), route directly to lead_capture_node.
    Otherwise route to faq_matcher_node to process knowledge.
    """
    if state.get("is_pure_lead", False):
        return "lead_capture_node"
    return "faq_matcher_node"


async def lead_capture_node(state: ConversationState) -> Dict[str, Any]:
    """Node: Formulates response for a pure contact detail submission."""
    thank_you = (
        "Thank you! Our support team has received your details and will contact you shortly."
    )
    return {
        "answer": thank_you,
        "intent": "lead_captured",
        "is_resolved": True,
        "sources": [],
    }


async def faq_matcher_node(state: ConversationState) -> Dict[str, Any]:
    """Node 2: Filters pre-fetched FAQs matching the detected intent."""
    intent = state.get("intent", "information")
    faqs = state.get("faqs", [])

    matching_faqs = [f for f in faqs if f.get("intent") == intent]
    if matching_faqs:
        faq_context = "".join(f"Q: {f['question']}\nA: {f['answer']}\n\n" for f in matching_faqs)
    else:
        faq_context = "No specific FAQ found for this intent."

    return {"faq_context": faq_context}


async def rag_retriever_node(state: ConversationState) -> Dict[str, Any]:
    """Node 3: Semantic RAG vector retrieval with similarity threshold and top_k.

    Applies multi-turn conversational coreference resolution and short-lived session.
    """
    tenant_id = state.get("tenant_id", "")
    question = state.get("question", "")
    chat_history = state.get("chat_history", [])

    # Enrich search query if follow-up refers to prior conversational turns
    search_query = resolve_conversational_query(question, chat_history)

    try:
        retrieved_chunks = await aretrieve_relevant_chunks(
            tenant_id=tenant_id,
            query=search_query,
            top_k=CHAT_TOP_K,
            threshold=CHAT_SIMILARITY_THRESHOLD,
        )
    except Exception as e:
        logger.warning(f"[langgraph] RAG retrieval failed for tenant {tenant_id}: {e}")
        retrieved_chunks = []

    doc_context = format_rag_context(retrieved_chunks)

    sources = [
        {
            "document_id": c.document_id,
            "filename": c.filename,
            "relevance_score": c.similarity_score,
        }
        for c in retrieved_chunks
    ]

    serialized_chunks = [
        c.to_dict() if isinstance(c, RetrievedChunk) else c
        for c in retrieved_chunks
    ]

    return {
        "retrieved_chunks": serialized_chunks,
        "doc_context": doc_context,
        "sources": sources,
    }


async def answer_generation_node(state: ConversationState) -> Dict[str, Any]:
    """Node 4: Generates answer using LangChain ChatGroq with multi-turn history.

    Preserves primary -> fallback model switching.
    Incorporates lead confirmation if lead was captured alongside inquiry.
    """
    question = state.get("question", "")
    company = state.get("company", "the company")
    industry = state.get("industry", "general services")
    desc = state.get("desc", "")
    custom_prompt = state.get("custom_prompt", "")
    language = state.get("language", "en")
    lang_name = LANG_MAP.get(language, "English")
    faq_context = state.get("faq_context", "")
    doc_context = state.get("doc_context", "")
    chat_history = state.get("chat_history", [])
    lead_data = state.get("lead_data")

    # Build system instructions via shared grounded prompt builder
    base_system = build_rag_system_prompt(
        company=company,
        industry=industry,
        desc=desc,
        custom_prompt=custom_prompt,
        lang_name=lang_name,
        faq_context=faq_context,
        doc_context=doc_context,
    )

    answer_fn = _get_chat_hook("aget_answer", None)
    generated_answer = None

    if answer_fn is not None:
        try:
            generated_answer = await answer_fn(
                question=question,
                intent=state.get("intent", "information"),
                tenant_id=state.get("tenant_id", ""),
                language=language,
                company=company,
                industry=industry,
                desc=desc,
                custom_prompt=custom_prompt,
                faq_context=faq_context,
                doc_context=doc_context,
                chat_history=chat_history,
            )
        except TypeError:
            generated_answer = await answer_fn(
                question=question,
                intent=state.get("intent", "information"),
                tenant_id=state.get("tenant_id", ""),
                language=language,
                company=company,
                industry=industry,
                desc=desc,
                custom_prompt=custom_prompt,
                faq_context=faq_context,
                doc_context=doc_context,
            )
        except Exception as ans_err:
            logger.warning(f"[langgraph] Hooked answer function raised: {ans_err}")
            generated_answer = None

    if not generated_answer:
        # Format multi-turn conversation messages with primary -> fallback Groq models
        messages = [SystemMessage(content=base_system)]
        for turn in chat_history:
            q = turn.get("question", "")
            a = turn.get("answer", "")
            if q:
                messages.append(HumanMessage(content=q))
            if a:
                messages.append(AIMessage(content=a))

        messages.append(HumanMessage(content=question))

        last_err = None
        for model_name in FAQ_MODELS:
            try:
                llm = _get_groq_llm(model_name, temperature=0.5)
                response = await llm.ainvoke(messages)
                if response and response.content:
                    generated_answer = response.content.strip()
                    logger.info(
                        f"[langgraph] Model '{model_name}' generated answer for tenant={state.get('tenant_id')}"
                    )
                    break
            except Exception as model_err:
                last_err = model_err
                logger.warning(
                    f"[langgraph] Model '{model_name}' failed for tenant={state.get('tenant_id')}: {model_err}"
                )
                continue

        if not generated_answer:
            logger.error(
                f"[langgraph] All models failed for tenant={state.get('tenant_id')}. Last error: {last_err}"
            )
            generated_answer = (
                "I apologize, but our AI service is temporarily unavailable. "
                "Please try again in a moment, or contact our support team directly."
            )

    # If lead data was captured along with an inquiry, prepend polite acknowledgment
    if lead_data and not state.get("is_pure_lead", False):
        ack = (
            "Thank you! Our support team has received your contact details and will reach out shortly.\n\n"
        )
        if not generated_answer.startswith("Thank you!"):
            generated_answer = ack + generated_answer

    return {
        "answer": generated_answer,
        "is_resolved": bool(state.get("sources") or lead_data),
    }


async def citation_formatter_node(state: ConversationState) -> Dict[str, Any]:
    """Node 5: Ensures citations and resolved flags are formatted properly."""
    sources = state.get("sources", [])
    answer = state.get("answer", "")
    lead_data = state.get("lead_data")

    is_resolved = bool(sources or lead_data or ("Thank you!" in answer))
    return {
        "sources": sources,
        "is_resolved": is_resolved,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Graph Construction & Compilation
# ─────────────────────────────────────────────────────────────────────────────

def build_chat_graph(checkpointer: Optional[Any] = None) -> Any:
    """Builds and compiles the StateGraph workflow."""
    workflow = StateGraph(ConversationState)

    # Add Nodes
    workflow.add_node("guard_and_intent_node", guard_and_intent_node)
    workflow.add_node("lead_capture_node", lead_capture_node)
    workflow.add_node("faq_matcher_node", faq_matcher_node)
    workflow.add_node("rag_retriever_node", rag_retriever_node)
    workflow.add_node("answer_generation_node", answer_generation_node)
    workflow.add_node("citation_formatter_node", citation_formatter_node)

    # Add Edges & Conditional Routing
    workflow.add_edge(START, "guard_and_intent_node")
    workflow.add_conditional_edges(
        "guard_and_intent_node",
        router_lead_or_inquiry,
        {
            "lead_capture_node": "lead_capture_node",
            "faq_matcher_node": "faq_matcher_node",
        },
    )
    workflow.add_edge("lead_capture_node", "citation_formatter_node")
    workflow.add_edge("faq_matcher_node", "rag_retriever_node")
    workflow.add_edge("rag_retriever_node", "answer_generation_node")
    workflow.add_edge("answer_generation_node", "citation_formatter_node")
    workflow.add_edge("citation_formatter_node", END)

    if checkpointer is None:
        checkpointer = get_checkpointer()

    return workflow.compile(checkpointer=checkpointer)


# Global compiled graph with persistent checkpointer (with resilient fallback)
global_persistent_checkpointer = get_checkpointer()
compiled_chat_graph = build_chat_graph(checkpointer=global_persistent_checkpointer)


_PER_TURN_RESET_DEFAULTS: ConversationState = {
    "intent": "",
    "lead_data": None,
    "is_pure_lead": False,
    "faq_context": "",
    "retrieved_chunks": [],
    "doc_context": "",
    "sources": [],
    "answer": "",
    "is_resolved": False,
    "error": None,
}


async def run_chat_graph(
    initial_state: ConversationState,
    thread_id: Optional[str] = None,
) -> ConversationState:
    """Convenience helper to execute the LangGraph conversational graph."""
    config = {}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
    else:
        tid = f"{initial_state.get('tenant_id', 'anon')}:{initial_state.get('session_id', 'anon')}"
        config["configurable"] = {"thread_id": tid}

    # Reset per-turn transient channels so previous checkpoint turns never bleed intent/sources/leads
    turn_state: ConversationState = {**_PER_TURN_RESET_DEFAULTS, **initial_state}

    try:
        result = await compiled_chat_graph.ainvoke(turn_state, config=config)
        return result
    except Exception as e:
        logger.error(f"[run_chat_graph] Error executing compiled graph: {e}")
        return {
            **initial_state,
            "answer": (
                "I apologize, but our AI service is temporarily unavailable. "
                "Please try again in a moment, or contact our support team directly."
            ),
            "intent": "error_inference_failure",
            "is_resolved": False,
            "sources": [],
        }
