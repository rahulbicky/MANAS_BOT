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
