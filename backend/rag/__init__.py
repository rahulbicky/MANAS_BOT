"""
backend/rag
-----------
Advanced Retrieval-Augmented Generation (RAG) module for ManasBot.
Provides intelligent text chunking, multilingual vector embedding,
semantic vector retrieval, document ingestion, and prompt synthesis.
"""
from .chunker import (
    chunk_document,
    DocumentChunkData,
    DEFAULT_CHUNK_SIZE,
    DEFAULT_CHUNK_OVERLAP,
    estimate_token_count,
)
from .embedder import (
    get_embedding_model,
    embed_query,
    embed_passages,
    aembed_query,
    aembed_passages,
    MODEL_NAME,
    EMBEDDING_DIM,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
)
from .retriever import (
    RetrievedChunk,
    retrieve_relevant_chunks,
    aretrieve_relevant_chunks,
    rerank_chunks,
    deduplicate_chunks,
    DEFAULT_TOP_K,
    DEFAULT_SIMILARITY_THRESHOLD,
)
from .ingestion import (
    ingest_document,
    delete_document_chunks,
    reingest_document,
)
from .prompts import (
    format_rag_context,
    get_rag_citation_instruction,
)
from .graph import (
    ConversationState,
    build_chat_graph,
    compiled_chat_graph,
    run_chat_graph,
    resolve_conversational_query,
)
from .checkpointer import (
    PostgresCheckpointSaver,
    AsyncPostgresSaver,
    get_checkpointer,
)
from .tools import (
    ToolExecutionResult,
    execute_knowledge_retrieval,
    execute_business_profile,
    execute_lead_capture,
    execute_support_incident,
    get_tenant_agent_tools,
)

__all__ = [
    "chunk_document",
    "DocumentChunkData",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    "estimate_token_count",
    "get_embedding_model",
    "embed_query",
    "embed_passages",
    "aembed_query",
    "aembed_passages",
    "MODEL_NAME",
    "EMBEDDING_DIM",
    "PASSAGE_PREFIX",
    "QUERY_PREFIX",
    "RetrievedChunk",
    "retrieve_relevant_chunks",
    "aretrieve_relevant_chunks",
    "rerank_chunks",
    "deduplicate_chunks",
    "DEFAULT_TOP_K",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "ingest_document",
    "delete_document_chunks",
    "reingest_document",
    "format_rag_context",
    "get_rag_citation_instruction",
    "ConversationState",
    "build_chat_graph",
    "compiled_chat_graph",
    "run_chat_graph",
    "resolve_conversational_query",
    "PostgresCheckpointSaver",
    "AsyncPostgresSaver",
    "get_checkpointer",
    "ToolExecutionResult",
    "execute_knowledge_retrieval",
    "execute_business_profile",
    "execute_lead_capture",
    "execute_support_incident",
    "get_tenant_agent_tools",
]
