import os
import logging
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from .database import get_tenant_session, FAQ, BusinessProfile, KnowledgeDocument

load_dotenv()
logger = logging.getLogger(__name__)

FAQ_MODELS = [
    "openai/gpt-oss-20b",   # primary: fast, cheap
    "llama3-8b-8192",       # fallback 1
    "gemma2-9b-it",         # fallback 2
]

LANG_MAP = {
    "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
    "de": "German", "pt": "Portuguese", "ar": "Arabic", "zh": "Chinese",
    "ja": "Japanese", "ko": "Korean", "ru": "Russian", "it": "Italian",
    "nl": "Dutch", "tr": "Turkish", "bn": "Bengali", "ta": "Tamil",
    "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada",
}


def _build_faq_prompt(
    company: str,
    industry: str,
    desc: str,
    custom_prompt: str,
    lang_name: str,
) -> ChatPromptTemplate:
    """Construct prompt template for FAQ chatbot."""
    if custom_prompt:
        system_prompt = (
            f"{custom_prompt}\n\n"
            f"LANGUAGE RULE: You MUST respond ONLY in {lang_name}.\n"
            f"FAQ Context:\n{{context}}\n\n"
            "{doc_context}"
        )
    else:
        system_prompt = (
            f"You are a strict customer support chatbot for {company} ({industry}). "
            f"Business Description: {desc}\n\n"
            "### ABSOLUTE RULES:\n"
            f"1. LANGUAGE: You MUST respond ONLY in {lang_name}. Translate your entire response into {lang_name}.\n"
            f"2. SCOPE: ONLY answer questions about {company} or the {industry} industry.\n"
            "3. NO HALLUCINATIONS: If the FAQ Context or Knowledge Base Documents below do not have the EXACT answer, you MUST NOT use your general LLM knowledge. You MUST NOT guess details like discounts, packs, or prices.\n"
            f"4. FALLBACK: For ANY question you cannot answer using the provided Contexts, you MUST respond with this exact phrase (translated into {lang_name}): 'I do apologize, but I do not have specific details on that right now. Please provide your Name, Phone Number, and Email address, and our support team will contact you shortly to provide the information you need.'\n"
            "5. VALIDATION: If the user provides their contact information, check for correctness strictly but politely:\n"
            "   - Phone Number: It MUST be exactly 10 digits long (e.g. 9004688543). If it is not exactly 10 digits or contains letters, politely ask: 'The phone number provided seems incorrect. Could you please provide a valid 10-digit number?' Do not apologize if the number is correct.\n"
            "   - Email: Must be a valid email format (e.g., name@example.com) with an '@' and a domain.\n"
            "   - If both Name, a valid 10-digit Phone, and Email are provided, you MUST reply ONLY with: 'Thank you! Our support team has received your details and will contact you shortly.' DO NOT restate their details or offer validation commentary.\n"
            "6. FORMAT: Use short, professional bullet points for answers.\n"
            "\n\nFAQ Context:\n{context}\n\n"
            "{doc_context}"
        )

    return ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])


def get_faq_context(intent: str, tenant_id: str, db=None) -> str:
    """Get FAQ context from a specific tenant's database."""
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    try:
        faqs = db.query(FAQ).filter(FAQ.tenant_id == tenant_id, FAQ.intent == intent, FAQ.is_active == True).all()
        if not faqs:
            return "No specific FAQ found for this intent."

        context = ""
        for faq in faqs:
            context += f"Q: {faq.question}\nA: {faq.answer}\n\n"
        return context
    finally:
        if should_close and db:
            db.close()


def get_document_context(tenant_id: str, db=None, max_chars: int = 5000) -> str:
    """Get context from uploaded Knowledge Documents with a character limit."""
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    try:
        docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.is_active == True).all()
        if not docs:
            return ""

        context = "### UPLOADED KNOWLEDGE BASE DOCUMENTS:\n"
        current_length = len(context)

        for doc in docs:
            doc_header = f"--- Document: {doc.filename} ---\n"
            doc_content = doc.content or ""

            # If adding this doc exceeds max_chars, truncate it
            if current_length + len(doc_header) + len(doc_content) > max_chars:
                remaining = max_chars - current_length - len(doc_header)
                if remaining > 100:
                    context += doc_header + doc_content[:remaining] + "... [truncated]\n\n"
                break
            else:
                context += doc_header + doc_content + "\n\n"
                current_length = len(context)

        return context
    finally:
        if should_close and db:
            db.close()


def get_answer(question: str, intent: str, tenant_id: str, language: str = "en", db=None) -> str:
    """Get AI answer using tenant-specific FAQs and business profile (synchronous). Preserved for backwards compatibility."""
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    try:
        try:
            with db.begin_nested():
                profile = db.query(
                    BusinessProfile.company_name,
                    BusinessProfile.industry,
                    BusinessProfile.business_description,
                    BusinessProfile.chatbot_system_prompt,
                ).filter(BusinessProfile.tenant_id == tenant_id).first()
        except Exception as profile_err:
            logger.warning(f"[faq_chain] Failed to load BusinessProfile for tenant {tenant_id}: {profile_err}")
            profile = None

        company = profile[0] if profile and profile[0] else "the company"
        industry = profile[1] if profile and profile[1] else "general services"
        desc = profile[2] if profile and profile[2] else ""
        custom_prompt = profile[3] if profile and profile[3] else ""
        lang_name = LANG_MAP.get(language, "English")

        context = get_faq_context(intent, tenant_id, db=db)
        doc_context = get_document_context(tenant_id, db=db, max_chars=8000)

        logger.info(f"[faq_chain] tenant={tenant_id} | company={company} | intent={intent} | lang={language} | faq_chars={len(context)} | doc_chars={len(doc_context)}")

        prompt = _build_faq_prompt(company, industry, desc, custom_prompt, lang_name)

        last_err = None
        for model_name in FAQ_MODELS:
            try:
                llm = ChatGroq(model=model_name, temperature=0.5)
                chain = prompt | llm
                response = chain.invoke({"question": question, "context": context, "doc_context": doc_context})
                logger.info(f"[faq_chain] Model '{model_name}' answered successfully for tenant={tenant_id}")
                return response.content.strip()
            except Exception as model_err:
                last_err = model_err
                logger.warning(f"[faq_chain] Model '{model_name}' failed for tenant={tenant_id}: {model_err}")
                continue

        logger.error(f"[faq_chain] All LLM models failed for tenant={tenant_id}. Last error: {last_err}")
        return "I apologize, but our AI service is temporarily unavailable. Please try again in a moment, or contact our support team directly."

    except Exception as e:
        import traceback
        logger.error(f"[faq_chain] Unexpected error for tenant={tenant_id}: {e}\n{traceback.format_exc()}")
        return "I apologize, but I encountered an error processing your request. Please try again later."
    finally:
        if should_close and db:
            db.close()


async def aget_answer(
    question: str,
    intent: str,
    tenant_id: str,
    language: str = "en",
    db=None,
    company: str = None,
    industry: str = None,
    desc: str = None,
    custom_prompt: str = None,
    faq_context: str = None,
    doc_context: str = None,
) -> str:
    """Get AI answer asynchronously using ChatGroq.ainvoke.

    If company, industry, faq_context and doc_context are provided, database access is
    completely bypassed, releasing DB connections back to the pool before LLM execution.
    """
    should_close = False
    try:
        # If any context field is missing, fetch from database
        if company is None or industry is None or desc is None or custom_prompt is None:
            if db is None:
                db = get_tenant_session(tenant_id)
                should_close = True
            try:
                with db.begin_nested():
                    profile = db.query(
                        BusinessProfile.company_name,
                        BusinessProfile.industry,
                        BusinessProfile.business_description,
                        BusinessProfile.chatbot_system_prompt,
                    ).filter(BusinessProfile.tenant_id == tenant_id).first()
            except Exception as profile_err:
                logger.warning(f"[faq_chain] Failed to load BusinessProfile for tenant {tenant_id}: {profile_err}")
                profile = None

            if company is None:
                company = profile[0] if profile and profile[0] else "the company"
            if industry is None:
                industry = profile[1] if profile and profile[1] else "general services"
            if desc is None:
                desc = profile[2] if profile and profile[2] else ""
            if custom_prompt is None:
                custom_prompt = profile[3] if profile and profile[3] else ""

        company = company or "the company"
        industry = industry or "general services"
        desc = desc or ""
        custom_prompt = custom_prompt or ""
        lang_name = LANG_MAP.get(language, "English")

        if faq_context is None:
            faq_context = get_faq_context(intent, tenant_id, db=db)
        if doc_context is None:
            doc_context = get_document_context(tenant_id, db=db, max_chars=8000)

        if should_close and db:
            db.close()
            db = None
            should_close = False

        logger.info(f"[faq_chain] async tenant={tenant_id} | company={company} | intent={intent} | lang={language} | faq_chars={len(faq_context)} | doc_chars={len(doc_context)}")

        prompt = _build_faq_prompt(company, industry, desc, custom_prompt, lang_name)

        last_err = None
        for model_name in FAQ_MODELS:
            try:
                llm = ChatGroq(model=model_name, temperature=0.5)
                chain = prompt | llm
                response = await chain.ainvoke({"question": question, "context": faq_context, "doc_context": doc_context})
                logger.info(f"[faq_chain] Async model '{model_name}' answered successfully for tenant={tenant_id}")
                return response.content.strip()
            except Exception as model_err:
                last_err = model_err
                logger.warning(f"[faq_chain] Async model '{model_name}' failed for tenant={tenant_id}: {model_err}")
                continue

        logger.error(f"[faq_chain] All async LLM models failed for tenant={tenant_id}. Last error: {last_err}")
        return "I apologize, but our AI service is temporarily unavailable. Please try again in a moment, or contact our support team directly."

    except Exception as e:
        import traceback
        logger.error(f"[faq_chain] Async unexpected error for tenant={tenant_id}: {e}\n{traceback.format_exc()}")
        return "I apologize, but I encountered an error processing your request. Please try again later."
    finally:
        if should_close and db:
            try:
                db.close()
            except Exception:
                pass


if __name__ == "__main__":
    print("Use with a valid tenant_id: get_answer('question', 'intent', 'tenant_id')")
