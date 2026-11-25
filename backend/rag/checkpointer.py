"""
backend/rag/checkpointer.py
---------------------------
PostgreSQL-backed persistent checkpoint saver for LangGraph.
Implements BaseCheckpointSaver[str] to provide multi-worker, multi-instance,
persistent conversational state storage backed by the central PostgreSQL database.

Features:
  - Reuses existing SQLAlchemy engine & connection pool
  - Zero connection holding during LLM inference (short-lived checkouts)
  - Strict tenant and session isolation via composite thread_id
  - Automatic idempotent table schema creation
  - Graceful fallback to MemorySaver if database is unreachable or SQLite is active
"""
import os
import sys
import logging
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from datetime import datetime, timezone

from langchain_core.runnables import RunnableConfig
from sqlalchemy import (
    create_engine,
    text,
    Table,
    Column,
    String,
    Integer,
    LargeBinary,
    DateTime,
    MetaData,
    Index,
    inspect,
)
from sqlalchemy.engine import Engine
from starlette.concurrency import run_in_threadpool

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    PendingWrite,
    get_checkpoint_id,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

logger = logging.getLogger(__name__)

_ALLOWED_MSGPACK_MODULES = [("backend.rag.retriever", "RetrievedChunk")]


def _default_serializer() -> JsonPlusSerializer:
    """Create JsonPlusSerializer permitting ManasBot's RetrievedChunk dataclass."""
    try:
        return JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
    except TypeError:
        return JsonPlusSerializer()


class PostgresCheckpointSaver(BaseCheckpointSaver[str]):
    """Production-grade PostgreSQL checkpoint saver for LangGraph."""

    def __init__(self, engine: Engine, serde: Optional[Any] = None) -> None:
        super().__init__(serde=serde or _default_serializer())
        self.engine = engine
        self._ensure_tables_exist()

    def _ensure_tables_exist(self) -> None:
        """Create checkpoint tables and indexes if they do not exist."""
        try:
            with self.engine.begin() as conn:
                dialect = self.engine.dialect.name
                blob_type = "BYTEA" if dialect == "postgresql" else "BLOB"
                dt_type = "TIMESTAMP WITH TIME ZONE" if dialect == "postgresql" else "TIMESTAMP"

                conn.execute(
                    text(f"""
                    CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        parent_checkpoint_id VARCHAR(255),
                        checkpoint_type VARCHAR(50) NOT NULL,
                        checkpoint_bytes {blob_type} NOT NULL,
                        metadata_type VARCHAR(50) NOT NULL,
                        metadata_bytes {blob_type} NOT NULL,
                        created_at {dt_type} NOT NULL,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                    );
                    """)
                )

                conn.execute(
                    text(f"""
                    CREATE TABLE IF NOT EXISTS langgraph_checkpoint_blobs (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        channel VARCHAR(255) NOT NULL,
                        version VARCHAR(255) NOT NULL,
                        blob_type VARCHAR(50) NOT NULL,
                        blob_bytes {blob_type} NOT NULL,
                        PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
                    );
                    """)
                )

                conn.execute(
                    text(f"""
                    CREATE TABLE IF NOT EXISTS langgraph_checkpoint_writes (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        task_id VARCHAR(255) NOT NULL,
                        idx INTEGER NOT NULL,
                        channel VARCHAR(255) NOT NULL,
                        write_type VARCHAR(50) NOT NULL,
                        write_bytes {blob_type} NOT NULL,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    );
                    """)
                )

                # Performance indexes for thread lookups
                if dialect == "postgresql":
                    conn.execute(
                        text("""
                        CREATE INDEX IF NOT EXISTS idx_lg_cp_lookup
                        ON langgraph_checkpoints (thread_id, checkpoint_ns, created_at DESC);
                        """)
                    )
            logger.info("[checkpointer] PostgreSQL checkpoint tables verified successfully.")
        except Exception as e:
            logger.warning(f"[checkpointer] Failed to initialize checkpoint tables: {e}")

    def _load_blobs(
        self, conn, thread_id: str, checkpoint_ns: str, versions: ChannelVersions
    ) -> Dict[str, Any]:
        """Fetch and deserialize channel values for requested channel versions."""
        if not versions:
            return {}
        result: Dict[str, Any] = {}
        for channel, ver in versions.items():
            row = conn.execute(
                text("""
                SELECT blob_type, blob_bytes FROM langgraph_checkpoint_blobs
                WHERE thread_id = :tid AND checkpoint_ns = :ns AND channel = :ch AND version = :ver
                """),
                {"tid": thread_id, "ns": checkpoint_ns, "ch": channel, "ver": str(ver)},
            ).first()
            if row and row[0] != "empty":
                try:
                    result[channel] = self.serde.loads_typed((row[0], bytes(row[1])))
                except Exception as ex:
                    logger.warning(f"[checkpointer] Error decoding blob {channel}:{ver}: {ex}")
        return result

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Retrieve a checkpoint tuple by thread_id and optional checkpoint_id."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id: Optional[str] = get_checkpoint_id(config)

        try:
            with self.engine.connect() as conn:
                if checkpoint_id:
                    row = conn.execute(
                        text("""
                        SELECT checkpoint_id, parent_checkpoint_id, checkpoint_type, checkpoint_bytes,
                               metadata_type, metadata_bytes
                        FROM langgraph_checkpoints
                        WHERE thread_id = :tid AND checkpoint_ns = :ns AND checkpoint_id = :cid
                        """),
                        {"tid": thread_id, "ns": checkpoint_ns, "cid": checkpoint_id},
                    ).first()
                else:
                    row = conn.execute(
                        text("""
                        SELECT checkpoint_id, parent_checkpoint_id, checkpoint_type, checkpoint_bytes,
                               metadata_type, metadata_bytes
                        FROM langgraph_checkpoints
                        WHERE thread_id = :tid AND checkpoint_ns = :ns
                        ORDER BY checkpoint_id DESC
                        LIMIT 1
                        """),
                        {"tid": thread_id, "ns": checkpoint_ns},
                    ).first()

                if not row:
                    return None

                cid, parent_cid, cp_type, cp_bytes, meta_type, meta_bytes = row
                ckpt_dict: Checkpoint = self.serde.loads_typed((cp_type, bytes(cp_bytes)))
                meta_dict = self.serde.loads_typed((meta_type, bytes(meta_bytes)))

                # Load channel values from blobs table
                channel_values = self._load_blobs(
                    conn, thread_id, checkpoint_ns, ckpt_dict.get("channel_versions", {})
                )

                # Load pending writes
                write_rows = conn.execute(
                    text("""
                    SELECT task_id, channel, write_type, write_bytes
                    FROM langgraph_checkpoint_writes
                    WHERE thread_id = :tid AND checkpoint_ns = :ns AND checkpoint_id = :cid
                    ORDER BY idx ASC
                    """),
                    {"tid": thread_id, "ns": checkpoint_ns, "cid": cid},
                ).all()

                pending_writes: List[PendingWrite] = []
                for wr in write_rows:
                    try:
                        val = self.serde.loads_typed((wr[2], bytes(wr[3])))
                        pending_writes.append((wr[0], wr[1], val))
                    except Exception:
                        pass

                parent_config = (
                    {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": parent_cid,
                        }
                    }
                    if parent_cid
                    else None
                )

                return CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": cid,
                        }
                    },
                    checkpoint={**ckpt_dict, "channel_values": channel_values},
                    metadata=meta_dict,
                    parent_config=parent_config,
                    pending_writes=pending_writes,
                )
        except Exception as e:
            logger.error(f"[checkpointer] Error reading checkpoint for thread {thread_id}: {e}")
            return None

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List checkpoint tuples matching the criteria."""
        if not config:
            return iter([])

        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        before_id = get_checkpoint_id(before) if before else None

        try:
            with self.engine.connect() as conn:
                query = """
                    SELECT checkpoint_id, parent_checkpoint_id, checkpoint_type, checkpoint_bytes,
                           metadata_type, metadata_bytes
                    FROM langgraph_checkpoints
                    WHERE thread_id = :tid AND checkpoint_ns = :ns
                """
                params: Dict[str, Any] = {"tid": thread_id, "ns": checkpoint_ns}
                if before_id:
                    query += " AND checkpoint_id < :before_id"
                    params["before_id"] = before_id

                query += " ORDER BY checkpoint_id DESC"
                if limit:
                    query += f" LIMIT {int(limit)}"

                rows = conn.execute(text(query), params).all()
                for row in rows:
                    cid, parent_cid, cp_type, cp_bytes, meta_type, meta_bytes = row
                    meta_dict = self.serde.loads_typed((meta_type, bytes(meta_bytes)))
                    if filter and not all(meta_dict.get(k) == v for k, v in filter.items()):
                        continue

                    ckpt_dict: Checkpoint = self.serde.loads_typed((cp_type, bytes(cp_bytes)))
                    channel_values = self._load_blobs(
                        conn, thread_id, checkpoint_ns, ckpt_dict.get("channel_versions", {})
                    )

                    parent_config = (
                        {
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": parent_cid,
                            }
                        }
                        if parent_cid
                        else None
                    )

                    yield CheckpointTuple(
                        config={
                            "configurable": {
                                "thread_id": thread_id,
                                "checkpoint_ns": checkpoint_ns,
                                "checkpoint_id": cid,
                            }
                        },
                        checkpoint={**ckpt_dict, "channel_values": channel_values},
                        metadata=meta_dict,
                        parent_config=parent_config,
                        pending_writes=[],
                    )
        except Exception as e:
            logger.error(f"[checkpointer] Error listing checkpoints for {thread_id}: {e}")

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Store a checkpoint and new channel version blobs atomically."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id: str = checkpoint["id"]
        parent_checkpoint_id: Optional[str] = config["configurable"].get("checkpoint_id")

        c = checkpoint.copy()
        values: Dict[str, Any] = c.pop("channel_values", {})
        versions_to_store = dict(new_versions)
        channel_versions = dict(c.get("channel_versions", {}))
        for ch in values:
            if ch not in versions_to_store:
                ver = channel_versions.get(ch, 1)
                versions_to_store[ch] = ver
                if ch not in channel_versions:
                    channel_versions[ch] = ver
        c["channel_versions"] = channel_versions

        cp_type, cp_bytes = self.serde.dumps_typed(c)
        meta_type, meta_bytes = self.serde.dumps_typed(metadata)
        now = datetime.now(timezone.utc)

        try:
            with self.engine.begin() as conn:
                # 1. Insert channel blobs for updated versions
                for channel, ver in versions_to_store.items():
                    if channel in values:
                        b_type, b_bytes = self.serde.dumps_typed(values[channel])
                    else:
                        b_type, b_bytes = ("empty", b"")

                    conn.execute(
                        text("""
                        INSERT INTO langgraph_checkpoint_blobs (thread_id, checkpoint_ns, channel, version, blob_type, blob_bytes)
                        VALUES (:tid, :ns, :ch, :ver, :btype, :bbytes)
                        ON CONFLICT (thread_id, checkpoint_ns, channel, version)
                        DO UPDATE SET blob_type = EXCLUDED.blob_type, blob_bytes = EXCLUDED.blob_bytes
                        """),
                        {
                            "tid": thread_id,
                            "ns": checkpoint_ns,
                            "ch": channel,
                            "ver": str(ver),
                            "btype": b_type,
                            "bbytes": b_bytes,
                        },
                    )

                # 2. Insert the checkpoint record
                conn.execute(
                    text("""
                    INSERT INTO langgraph_checkpoints (
                        thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                        checkpoint_type, checkpoint_bytes, metadata_type, metadata_bytes, created_at
                    ) VALUES (
                        :tid, :ns, :cid, :pcid, :cp_type, :cp_bytes, :meta_type, :meta_bytes, :now
                    )
                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id)
                    DO UPDATE SET
                        checkpoint_type = EXCLUDED.checkpoint_type,
                        checkpoint_bytes = EXCLUDED.checkpoint_bytes,
                        metadata_type = EXCLUDED.metadata_type,
                        metadata_bytes = EXCLUDED.metadata_bytes
                    """),
                    {
                        "tid": thread_id,
                        "ns": checkpoint_ns,
                        "cid": checkpoint_id,
                        "pcid": parent_checkpoint_id,
                        "cp_type": cp_type,
                        "cp_bytes": cp_bytes,
                        "meta_type": meta_type,
                        "meta_bytes": meta_bytes,
                        "now": now,
                    },
                )

            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            }
        except Exception as e:
            logger.error(f"[checkpointer] Error writing checkpoint for {thread_id}/{checkpoint_id}: {e}")
            return config

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Store pending intermediate writes from tasks."""
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id: str = config["configurable"]["checkpoint_id"]

        try:
            with self.engine.begin() as conn:
                for idx, (channel, val) in enumerate(writes):
                    w_type, w_bytes = self.serde.dumps_typed(val)
                    conn.execute(
                        text("""
                        INSERT INTO langgraph_checkpoint_writes (
                            thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, write_type, write_bytes
                        ) VALUES (
                            :tid, :ns, :cid, :task_id, :idx, :ch, :wtype, :wbytes
                        )
                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                        DO NOTHING
                        """),
                        {
                            "tid": thread_id,
                            "ns": checkpoint_ns,
                            "cid": checkpoint_id,
                            "task_id": task_id,
                            "idx": idx,
                            "ch": channel,
                            "wtype": w_type,
                            "wbytes": w_bytes,
                        },
                    )
        except Exception as e:
            logger.error(f"[checkpointer] Error writing task writes for {thread_id}: {e}")

    # ── Async Method Implementations (Offloaded to Worker Threadpool) ────────
    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        return await run_in_threadpool(self.get_tuple, config)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ):
        tuples = await run_in_threadpool(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for t in tuples:
            yield t

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await run_in_threadpool(self.put, config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        await run_in_threadpool(self.put_writes, config, writes, task_id, task_path)


# Alias for backward compatibility with LangGraph naming convention
AsyncPostgresSaver = PostgresCheckpointSaver


def _build_memory_saver() -> MemorySaver:
    """Instantiate MemorySaver with project serializer configuration."""
    try:
        return MemorySaver(serde=_default_serializer())
    except TypeError:
        return MemorySaver()


def get_checkpointer(engine: Optional[Engine] = None) -> BaseCheckpointSaver:
    """Factory creating a production-appropriate checkpointer with resilient fallback.

    Respects CHAT_CHECKPOINTER_BACKEND ('auto', 'postgres', 'memory').
    If a valid PostgreSQL engine is available, returns PostgresCheckpointSaver.
    If database connectivity fails or SQLite is used in auto mode, logs a notice and returns MemorySaver.
    """
    backend_pref = os.getenv("CHAT_CHECKPOINTER_BACKEND", "auto").strip().lower()
    if backend_pref == "memory":
        logger.info("[checkpointer] CHAT_CHECKPOINTER_BACKEND=memory; using MemorySaver.")
        return _build_memory_saver()

    if engine is None:
        try:
            from ..database import _get_central_engine
            engine = _get_central_engine()
        except Exception as e:
            logger.warning(f"[checkpointer] Could not retrieve central engine: {e}. Falling back to MemorySaver.")
            return _build_memory_saver()

    try:
        dialect_name = getattr(getattr(engine, "dialect", None), "name", "")
        if dialect_name == "sqlite" and backend_pref != "postgres":
            logger.info("[checkpointer] SQLite backend active in auto mode; using MemorySaver.")
            return _build_memory_saver()

        # Test basic engine responsiveness
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return PostgresCheckpointSaver(engine=engine)
    except Exception as ex:
        logger.warning(
            f"[checkpointer] PostgreSQL connection check failed ({ex}). Gracefully falling back to MemorySaver."
        )
        return _build_memory_saver()
