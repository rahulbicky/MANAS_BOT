"""
backend/rag/prompts.py
----------------------
Prompt engineering and context formatting utilities for ManasBot Advanced RAG.
Transforms retrieved semantic chunks into structured, attributed context blocks
and enforces factual grounding and citation instructions in Groq LLM prompts.
"""
from typing import List
from .retriever import RetrievedChunk


def format_rag_context(chunks: List[RetrievedChunk], max_tokens: int = 2500) -> str:
    """
    Format semantically retrieved chunks into a structured context string for LLM prompts.
    Includes document filenames and similarity relevance percentages.

    Args:
        chunks: List of RetrievedChunk objects ordered by descending relevance.
        max_tokens: Approximate token ceiling for RAG context (default: 2500).

    Returns:
        Formatted context block with source headers.
    """
    if not chunks:
        return ""

    context_lines = ["### VERIFIED KNOWLEDGE BASE CONTEXT (Top Relevant Excerpts):"]
    current_chars = len(context_lines[0])
    max_chars = max_tokens * 4

    for idx, chunk in enumerate(chunks, 1):
        relevance_pct = int(round(chunk.similarity_score * 100))
        header = f"\n--- [Source {idx}: {chunk.filename} | Relevance: {relevance_pct}%] ---"
        body = chunk.chunk_text.strip()
        addition = f"{header}\n{body}\n"

        if current_chars + len(addition) > max_chars:
            rem = max_chars - current_chars - len(header) - 10
            if rem > 100:
                context_lines.append(f"{header}\n{body[:rem]}... [truncated]\n")
            break

        context_lines.append(addition)
        current_chars += len(addition)

    return "\n".join(context_lines)


def get_rag_citation_instruction() -> str:
    """
    Standard prompt instruction for factual citation and grounding.
    """
    return (
        "CITATION INSTRUCTIONS:\n"
        "When providing answers based on the 'VERIFIED KNOWLEDGE BASE CONTEXT', "
        "cite the source file name in brackets at the end of the relevant sentence or paragraph "
        "(for example: '[Source: Return_Policy.pdf]'). Do not fabricate document names or citations."
    )


def build_rag_system_prompt(
    company: str,
    industry: str,
    desc: str,
    custom_prompt: str,
    lang_name: str,
    faq_context: str = "{context}",
    doc_context: str = "{doc_context}",
) -> str:
    """Shared system prompt builder enforcing multi-tenant grounding and anti-hallucination rules."""
    if custom_prompt:
        return (
            f"{custom_prompt}\n\n"
            f"LANGUAGE RULE: You MUST respond ONLY in {lang_name}.\n"
            f"FAQ Context:\n{faq_context}\n\n"
            f"{doc_context}"
        )
    return (
        f"You are a strict customer support chatbot for {company} ({industry}). "
        f"Business Description: {desc}\n\n"
        "### ABSOLUTE RULES:\n"
        f"1. LANGUAGE: You MUST respond ONLY in {lang_name}. Translate your entire response into {lang_name}.\n"
        f"2. SCOPE: ONLY answer questions about {company} or the {industry} industry.\n"
        "3. NO HALLUCINATIONS: If the FAQ Context or Knowledge Base Documents below do not have the EXACT answer, "
        "you MUST NOT use your general LLM knowledge. You MUST NOT guess details like discounts, packs, or prices.\n"
        f"4. FALLBACK: For ANY question you cannot answer using the provided Contexts, you MUST respond with this exact phrase (translated into {lang_name}): "
        "'I do apologize, but I do not have specific details on that right now. Please provide your Name, Phone Number, and Email address, "
        "and our support team will contact you shortly to provide the information you need.'\n"
        "5. VALIDATION: If the user provides their contact information, check for correctness strictly but politely:\n"
        "   - Phone Number: It MUST be exactly 10 digits long (e.g. 9004688543). If it is not exactly 10 digits or contains letters, politely ask: 'The phone number provided seems incorrect. Could you please provide a valid 10-digit number?' Do not apologize if the number is correct.\n"
        "   - Email: Must be a valid email format (e.g., name@example.com) with an '@' and a domain.\n"
        "   - If both Name, a valid 10-digit Phone, and Email are provided, you MUST reply ONLY with: 'Thank you! Our support team has received your details and will contact you shortly.' DO NOT restate their details or offer validation commentary.\n"
        "6. FORMAT: Use short, professional bullet points for answers.\n"
        "7. CITATIONS: When using information from the 'VERIFIED KNOWLEDGE BASE CONTEXT', "
        "cite the document filename in brackets (e.g. '[Source: Return_Policy.pdf]'). Do not fabricate citations.\n"
        f"\n\nFAQ Context:\n{faq_context}\n\n"
        f"{doc_context}"
    )
