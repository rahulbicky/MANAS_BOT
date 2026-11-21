"""
backend/rag/embedder.py
-----------------------
Local, CPU-optimized multilingual embedding engine for ManasBot Advanced RAG.
Uses FastEmbed with 'intfloat/multilingual-e5-small' generating 384-dimensional
normalized vector embeddings.

Enforces E5 model prefix requirements:
- 'passage: ' for document chunks.
- 'query: ' for user search queries.
"""
import logging
import threading
from typing import List, Optional
import numpy as np
from starlette.concurrency import run_in_threadpool

from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

logger = logging.getLogger(__name__)

MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "

_model_lock = threading.Lock()
_embedding_instance: Optional[TextEmbedding] = None


def _ensure_custom_model_registered() -> None:
    """Register intfloat/multilingual-e5-small with FastEmbed if not already registered."""
    try:
        supported_models = [m["model"].lower() for m in TextEmbedding.list_supported_models()]
        if MODEL_NAME.lower() not in supported_models:
            TextEmbedding.add_custom_model(
                model=MODEL_NAME,
                pooling=PoolingType.MEAN,
                normalization=True,
                sources=ModelSource(hf="intfloat/multilingual-e5-small"),
                dim=EMBEDDING_DIM,
                model_file="onnx/model.onnx",
                description="Multilingual E5 Small text embedding model (384 dimensions)",
                license="mit",
                additional_files=[
                    "onnx/sentencepiece.bpe.model",
                    "onnx/special_tokens_map.json",
                    "onnx/tokenizer.json",
                    "onnx/tokenizer_config.json",
                ],
            )
            logger.info(f"[embedder] Registered custom model '{MODEL_NAME}' ({EMBEDDING_DIM}d) with FastEmbed.")
    except Exception as e:
        # If already registered in a concurrent thread or previous run
        logger.debug(f"[embedder] Model registration notice: {e}")


def get_embedding_model() -> TextEmbedding:
    """
    Thread-safe singleton accessor for the FastEmbed multilingual embedding model.
    Loads ONNX model weights once into memory on CPU.
    """
    global _embedding_instance
    if _embedding_instance is not None:
        return _embedding_instance

    with _model_lock:
        if _embedding_instance is None:
            _ensure_custom_model_registered()
            logger.info(f"[embedder] Initializing FastEmbed model '{MODEL_NAME}' on CPU...")
            _embedding_instance = TextEmbedding(model_name=MODEL_NAME)
            logger.info(f"[embedder] Successfully loaded '{MODEL_NAME}' (dim={EMBEDDING_DIM}).")
        return _embedding_instance


def _format_passage(text: str) -> str:
    """Ensure passage has the required E5 prefix without duplication."""
    text_clean = text.strip() if text else ""
    if text_clean.startswith(PASSAGE_PREFIX):
        return text_clean
    return f"{PASSAGE_PREFIX}{text_clean}"


def _format_query(text: str) -> str:
    """Ensure query has the required E5 prefix without duplication."""
    text_clean = text.strip() if text else ""
    if text_clean.startswith(QUERY_PREFIX):
        return text_clean
    return f"{QUERY_PREFIX}{text_clean}"


def embed_query(query: str) -> List[float]:
    """
    Generate a 384-dimensional normalized vector for a search query.

    Args:
        query: User question or search query string.

    Returns:
        List of 384 float values.
    """
    if not query or not query.strip():
        return [0.0] * EMBEDDING_DIM

    model = get_embedding_model()
    formatted = _format_query(query)
    embeddings = list(model.embed([formatted]))
    if not embeddings:
        return [0.0] * EMBEDDING_DIM
    return embeddings[0].tolist()


def embed_passages(passages: List[str], batch_size: int = 32) -> List[List[float]]:
    """
    Generate 384-dimensional normalized vectors for a batch of document passages.

    Args:
        passages: List of document chunk text strings.
        batch_size: Inference batch size for ONNX runtime (default: 32).

    Returns:
        List of float vectors, each of length 384.
    """
    if not passages:
        return []

    model = get_embedding_model()
    formatted = [_format_passage(p) for p in passages]
    embeddings_iter = model.embed(formatted, batch_size=batch_size)
    return [vec.tolist() for vec in embeddings_iter]


async def aembed_query(query: str) -> List[float]:
    """Asynchronously generate a query embedding by offloading to the worker threadpool."""
    return await run_in_threadpool(embed_query, query)


async def aembed_passages(passages: List[str], batch_size: int = 32) -> List[List[float]]:
    """Asynchronously generate passage embeddings by offloading to the worker threadpool."""
    return await run_in_threadpool(embed_passages, passages, batch_size)
