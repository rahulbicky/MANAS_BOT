"""
backend/app/core/session_lock.py
--------------------------------
Session-level concurrency protection for ManasBot.
Serializes concurrent requests hitting the same (tenant_id, session_id) identity,
preventing race conditions in multi-turn history and checkpoint state.

Strategies:
  1. PostgreSQL Advisory Locks (Multi-worker & Multi-container safe across Uvicorn workers).
  2. In-Memory Reference-Counted Async Lock Registry (SQLite / local fallback with zero memory leak).
"""
import sys
import time
import asyncio
import hashlib
import logging
import threading
from typing import Optional, Dict
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.engine import Engine
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)

DEFAULT_LOCK_TIMEOUT_SECONDS: float = 10.0


class SessionLockTimeoutError(Exception):
    """Raised when acquiring a lock on a conversation session exceeds the timeout."""
    pass


def session_to_advisory_lock_id(tenant_id: str, session_id: str) -> int:
    """Generate a stable 64-bit signed integer for PostgreSQL advisory locks."""
    key = f"{tenant_id}:{session_id}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)

class _AsyncGlobalLockAdapter:
    """Provides backward-compatible async and sync context manager interface for internal lock."""
    def __init__(self, thread_lock: threading.Lock):
        self._thread_lock = thread_lock

    async def __aenter__(self):
        self._thread_lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._thread_lock.release()

    def __enter__(self):
        self._thread_lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._thread_lock.release()

class LocalSessionLockRegistry:
    """In-memory async lock registry with reference counting to prevent memory leaks."""

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._ref_counts: Dict[str, int] = {}
        self._thread_lock = threading.Lock()
        self._global_lock = _AsyncGlobalLockAdapter(self._thread_lock)

    async def acquire(self, key: str, timeout: float) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._thread_lock:
            existing = self._locks.get(key)
            is_stale = False
            if existing is not None:
                try:
                    is_stale = (existing._get_loop() != loop)
                except RuntimeError:
                    is_stale = True

            if existing is None or is_stale:
                self._locks[key] = asyncio.Lock()
                self._ref_counts[key] = 0
            self._ref_counts[key] += 1
            lock = self._locks[key]

        start_time = time.monotonic()
        acquired = False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            acquired = True
            return lock
        except asyncio.TimeoutError:
            raise SessionLockTimeoutError(
                f"Timeout ({timeout}s) waiting for session lock '{key}'."
            )
        finally:
            if not acquired:
                with self._thread_lock:
                    if key in self._ref_counts:
                        self._ref_counts[key] -= 1
                        if self._ref_counts[key] <= 0:
                            self._locks.pop(key, None)
                            self._ref_counts.pop(key, None)

    async def release(self, key: str, lock: asyncio.Lock) -> None:
        try:
            if lock.locked():
                lock.release()
        finally:
            with self._thread_lock:
                if key in self._ref_counts:
                    self._ref_counts[key] -= 1
                    if self._ref_counts[key] <= 0:
                        self._locks.pop(key, None)
                        self._ref_counts.pop(key, None)


_local_registry = LocalSessionLockRegistry()
_lock_registry = _local_registry


@asynccontextmanager
async def session_lock(
    tenant_id: str,
    session_id: str,
    timeout: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    timeout_seconds: Optional[float] = None,
    engine: Optional[Engine] = None,
):
    """Asynchronous context manager providing session-level mutual exclusion.

    If connected to PostgreSQL, uses pg_try_advisory_lock for multi-worker safety.
    If SQLite or local dev, uses LocalSessionLockRegistry.
    """
    if timeout_seconds is not None:
        timeout = timeout_seconds
    key = f"{tenant_id}:{session_id}"

    # Determine whether PostgreSQL advisory locking can be used
    use_postgres = False
    if engine is None:
        try:
            from ...database import _get_central_engine
            engine = _get_central_engine()
        except Exception:
            engine = None

    if engine and hasattr(engine, "dialect") and engine.dialect.name == "postgresql":
        use_postgres = True

    if use_postgres and engine is not None:
        lock_id = session_to_advisory_lock_id(tenant_id, session_id)
        start_time = time.monotonic()
        conn = None
        locked = False

        try:
            conn = await run_in_threadpool(engine.connect)
            while time.monotonic() - start_time < timeout:
                result = await run_in_threadpool(
                    lambda: conn.execute(
                        text("SELECT pg_try_advisory_lock(:id)"), {"id": lock_id}
                    ).scalar()
                )
                if result:
                    locked = True
                    break
                await asyncio.sleep(0.05)

            if not locked:
                raise SessionLockTimeoutError(
                    f"Timeout ({timeout}s) acquiring PostgreSQL advisory lock for session {key}."
                )

            logger.debug(f"[session_lock] Acquired PG advisory lock for {key}")
            yield

        finally:
            if conn and locked:
                try:
                    await run_in_threadpool(
                        lambda: conn.execute(
                            text("SELECT pg_advisory_unlock(:id)"), {"id": lock_id}
                        )
                    )
                    logger.debug(f"[session_lock] Released PG advisory lock for {key}")
                except Exception as unlock_err:
                    logger.warning(f"[session_lock] Error unlocking {key}: {unlock_err}")
            if conn:
                try:
                    await run_in_threadpool(conn.close)
                except Exception:
                    pass
    else:
        # SQLite / in-memory local lock registry
        lock = await _local_registry.acquire(key, timeout=timeout)
        try:
            logger.debug(f"[session_lock] Acquired in-memory lock for {key}")
            yield
        finally:
            await _local_registry.release(key, lock)
            logger.debug(f"[session_lock] Released in-memory lock for {key}")
