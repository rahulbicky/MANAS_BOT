import os
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv
from .database import get_tenant_session, FAQ, BusinessProfile, KnowledgeDocument

load_dotenv()


def get_faq_context(intent: str, tenant_id: str, db=None) -> str:
    """Get FAQ context from a specific tenant's database."""
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    faqs = db.query(FAQ).filter(FAQ.tenant_id == tenant_id, FAQ.intent == intent, FAQ.is_active == True).all()

    if should_close:
        db.close()

    if not faqs:
        return "No specific FAQ found for this intent."

    context = ""
    for faq in faqs:
        context += f"Q: {faq.question}\nA: {faq.answer}\n\n"
    return context


def get_document_context(tenant_id: str, db=None, max_chars: int = 5000) -> str:
    """Get context from uploaded Knowledge Documents with a character limit."""
    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.tenant_id == tenant_id, KnowledgeDocument.is_active == True).all()

    if should_close:
        db.close()

    if not docs:
        return ""

    context = "### UPLOADED KNOWLEDGE BASE DOCUMENTS:\n"
    current_length = len(context)

    for doc in docs:
        doc_header = f"--- Document: {doc.filename} ---\n"
        doc_content = doc.content

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


def get_answer(question: str, intent: str, tenant_id: str, language: str = "en", db=None) -> str:
    """Get AI answer using tenant-specific FAQs and business profile."""
    import logging
    logger = logging.getLogger(__name__)

    should_close = False
    if db is None:
        db = get_tenant_session(tenant_id)
        should_close = True

    try:
        # Query only the columns used by this flow to tolerate older tenant schemas.
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

        # Map language codes to full names
        lang_map = {
            "en": "English", "hi": "Hindi", "es": "Spanish", "fr": "French",
            "de": "German", "pt": "Portuguese", "ar": "Arabic", "zh": "Chinese",
            "ja": "Japanese", "ko": "Korean", "ru": "Russian", "it": "Italian",
            "nl": "Dutch", "tr": "Turkish", "bn": "Bengali", "ta": "Tamil",
            "te": "Telugu", "mr": "Marathi", "gu": "Gujarati", "kn": "Kannada",
        }
        lang_name = lang_map.get(language, "English")

        # Reuse the existing session for context fetching
        context = get_faq_context(intent, tenant_id, db=db)
        doc_context = get_document_context(tenant_id, db=db, max_chars=8000)

        logger.info(f"[faq_chain] tenant={tenant_id} | company={company} | intent={intent} | lang={language} | faq_chars={len(context)} | doc_chars={len(doc_context)}")

        # Build system prompt — use custom_prompt if admin set one, else use default
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

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{question}")
        ])

        # Try models in order — fallback if primary is unavailable
        _models = [
            "openai/gpt-oss-20b",   # primary: fast, cheap
            "llama3-8b-8192",       # fallback 1
            "gemma2-9b-it",         # fallback 2
        ]
        last_err = None
        for model_name in _models:
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

        # All models failed
        logger.error(f"[faq_chain] All LLM models failed for tenant={tenant_id}. Last error: {last_err}")
        return "I apologize, but our AI service is temporarily unavailable. Please try again in a moment, or contact our support team directly."

    except Exception as e:
        import traceback
        logger.error(f"[faq_chain] Unexpected error for tenant={tenant_id}: {e}\n{traceback.format_exc()}")
        return "I apologize, but I encountered an error processing your request. Please try again later."
    finally:
        if should_close:
            db.close()



if __name__ == "__main__":
    # Test requires a valid tenant_id
    print("Use with a valid tenant_id: get_answer('question', 'intent', 'tenant_id')")
