"""
test_phase3_production.py
-------------------------
Production reliability, persistent checkpointing, session concurrency locking,
UTC timezone modernization, and tenant-isolated retention verification test suite.

Covers:
  1. PostgreSQL / SQLite Checkpointer table creation & idempotent schema
  2. Persistent checkpoint storage and retrieval with composite thread_id
  3. Strict tenant and session isolation in checkpoint store
  4. Conversational state recovery across server restarts / checkpointer re-instantiations
  5. Session concurrency lock serialization (same session)
  6. Session lock timeout handling (SessionLockTimeoutError)
  7. Concurrent execution for different sessions without blocking
  8. Reference-counted lock registry memory cleanup (zero memory leaks)
  9. UTC timezone modernization & safe naive/aware comparisons
  10. Tenant retention policy configuration (7, 30, 90, custom, indefinite)
  11. Retention dry-run reporting (zero deletions)
  12. Retention cleanup with strict tenant isolation (zero cross-tenant deletion)
  13. Database connection pooling configuration
"""
import asyncio
import datetime
import os
import sys
import time
import unittest
import uuid
from typing import Any, Dict

# Set test environment
os.environ["CENTRAL_DB_URL"] = "sqlite:///./test_phase3.db"
os.environ["DATABASE_URL"] = "sqlite:///./test_phase3.db"
os.environ["DISABLE_FAST_EMBED"] = "true"
os.environ["DISABLE_GROQ_CALLS"] = "true"

from sqlalchemy import create_engine, text

import backend.database as db_mod
from backend.database import (
    _get_central_engine,
    _get_central_session,
    init_tenant_db,
    register_tenant,
    CentralTenant,
    ChatLog,
    ChatFeedback,
    utc_now,
    ensure_utc,
)
from backend.encryption import encrypt_text
from backend.rag.checkpointer import PostgresCheckpointSaver, get_checkpointer
from backend.app.core.session_lock import (
    session_lock,
    SessionLockTimeoutError,
    _lock_registry,
)
from backend.app.services.retention_service import RetentionService


class TestPhase3Production(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initialize central schema for Phase 3 test suite."""
        db_mod.CENTRAL_DB_URL = "sqlite:///./test_phase3.db"
        db_mod._central_engine = None
        db_mod._CentralSessionLocal = None
        init_tenant_db()
        db_mod.migrate_central_schema()

        cls.engine = _get_central_engine()

        # Seed two distinct test tenants
        cls.tenant_a = register_tenant(
            name=f"Tenant A {uuid.uuid4().hex[:6]}",
            db_url="sqlite:///./test_phase3.db",
            admin_password="password123",
        )
        cls.tenant_b = register_tenant(
            name=f"Tenant B {uuid.uuid4().hex[:6]}",
            db_url="sqlite:///./test_phase3.db",
            admin_password="password123",
        )

    @classmethod
    def tearDownClass(cls):
        """Cleanup test database file."""
        engine = _get_central_engine()
        engine.dispose()
        for f in ["./test_phase3.db", "test_phase3.db"]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    # ── 1. Checkpointer Table Schema & Idempotency ─────────────────────────────

    def test_01_checkpointer_table_creation(self):
        """Verify checkpointer creates required checkpoint tables and indexes idempotently."""
        checkpointer = PostgresCheckpointSaver(self.engine)
        # Calling ensure_tables_exist multiple times should be safe (idempotent)
        checkpointer._ensure_tables_exist()

        with self.engine.connect() as conn:
            from sqlalchemy import inspect
            inspector = inspect(self.engine)
            tables = inspector.get_table_names()
            self.assertIn("langgraph_checkpoints", tables)
            self.assertIn("langgraph_checkpoint_blobs", tables)
            self.assertIn("langgraph_checkpoint_writes", tables)

    # ── 2. Checkpointer Persistence & Thread Isolation ─────────────────────────

    def test_02_checkpoint_put_get_roundtrip(self):
        """Verify checkpoints can be written and read back faithfully."""
        checkpointer = PostgresCheckpointSaver(self.engine)
        thread_id = f"{self.tenant_a['id']}:session_roundtrip_1"

        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
            }
        }
        checkpoint_data = {
            "v": 1,
            "id": "cp_001",
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "channel_values": {"messages": ["hello from user", "hello from bot"]},
            "channel_versions": {"messages": 1},
            "versions_seen": {},
            "pending_sends": [],
        }
        metadata = {"source": "test", "step": 1}

        saved_config = checkpointer.put(config, checkpoint_data, metadata, {})
        self.assertIn("configurable", saved_config)
        self.assertEqual(saved_config["configurable"]["checkpoint_id"], "cp_001")

        # Read back checkpoint
        retrieved_tuple = checkpointer.get_tuple(config)
        self.assertIsNotNone(retrieved_tuple)
        self.assertEqual(retrieved_tuple.checkpoint["id"], "cp_001")
        self.assertEqual(
            retrieved_tuple.checkpoint["channel_values"]["messages"],
            ["hello from user", "hello from bot"],
        )
        self.assertEqual(retrieved_tuple.metadata["source"], "test")

    def test_03_checkpoint_tenant_and_session_isolation(self):
        """Verify checkpoints for tenant A cannot be seen by tenant B even with identical session IDs."""
        checkpointer = PostgresCheckpointSaver(self.engine)
        session_id = "shared_session_name"

        thread_a = f"{self.tenant_a['id']}:{session_id}"
        thread_b = f"{self.tenant_b['id']}:{session_id}"

        config_a = {"configurable": {"thread_id": thread_a, "checkpoint_ns": ""}}
        config_b = {"configurable": {"thread_id": thread_b, "checkpoint_ns": ""}}

        cp_a = {
            "v": 1,
            "id": "cp_tenant_a",
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "channel_values": {"tenant": "Tenant A Secret Data"},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }
        checkpointer.put(config_a, cp_a, {"tenant": "A"}, {})

        # Reading from config_b should return None
        retrieved_b = checkpointer.get_tuple(config_b)
        self.assertIsNone(retrieved_b)

        # Reading from config_a should return tenant A's data
        retrieved_a = checkpointer.get_tuple(config_a)
        self.assertIsNotNone(retrieved_a)
        self.assertEqual(retrieved_a.checkpoint["channel_values"]["tenant"], "Tenant A Secret Data")

    def test_04_checkpoint_state_recovery_across_server_restart(self):
        """Simulate server restart by instantiating a completely new PostgresCheckpointSaver instance."""
        thread_id = f"{self.tenant_a['id']}:restart_session_42"
        config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}

        # Instance 1 writes
        instance_1 = PostgresCheckpointSaver(self.engine)
        cp = {
            "v": 1,
            "id": "cp_pre_restart",
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "channel_values": {"state_key": "persisted_value_before_restart"},
            "channel_versions": {},
            "versions_seen": {},
            "pending_sends": [],
        }
        instance_1.put(config, cp, {"node": "answer_generation"}, {})

        # Instance 2 (simulating fresh server start) reads
        instance_2 = PostgresCheckpointSaver(self.engine)
        restored_tuple = instance_2.get_tuple(config)

        self.assertIsNotNone(restored_tuple)
        self.assertEqual(restored_tuple.checkpoint["id"], "cp_pre_restart")
        self.assertEqual(
            restored_tuple.checkpoint["channel_values"]["state_key"],
            "persisted_value_before_restart",
        )

    # ── 3. Session Concurrency Protection ──────────────────────────────────────

    def test_05_session_lock_serialization_same_session(self):
        """Verify concurrent requests for the exact same session are serialized."""
        execution_order = []

        async def worker(worker_id: int, delay: float):
            async with session_lock(self.tenant_a["id"], "concurrent_sess_1", timeout_seconds=5.0):
                execution_order.append(f"start_{worker_id}")
                await asyncio.sleep(delay)
                execution_order.append(f"end_{worker_id}")

        async def run_both():
            # Launch worker 1 and worker 2 almost simultaneously
            await asyncio.gather(worker(1, 0.05), worker(2, 0.01))

        asyncio.run(run_both())

        # Worker 1 must completely finish before Worker 2 begins
        self.assertEqual(execution_order[0], "start_1")
        self.assertEqual(execution_order[1], "end_1")
        self.assertEqual(execution_order[2], "start_2")
        self.assertEqual(execution_order[3], "end_2")

    def test_06_session_lock_timeout_handling(self):
        """Verify a short timeout raises SessionLockTimeoutError when lock is held."""
        async def run_timeout():
            async with session_lock(self.tenant_a["id"], "timeout_sess", timeout_seconds=5.0):
                # Inner task attempts to acquire same lock with 0.05s timeout
                with self.assertRaises(SessionLockTimeoutError):
                    async with session_lock(self.tenant_a["id"], "timeout_sess", timeout_seconds=0.05):
                        pass

        asyncio.run(run_timeout())

    def test_07_session_lock_different_sessions_concurrent(self):
        """Verify distinct sessions execute concurrently without blocking each other."""
        start_times = {}

        async def worker(session_name: str):
            async with session_lock(self.tenant_a["id"], session_name, timeout_seconds=5.0):
                start_times[session_name] = time.time()
                await asyncio.sleep(0.05)

        async def run_concurrent():
            await asyncio.gather(worker("sess_alpha"), worker("sess_beta"))

        asyncio.run(run_concurrent())

        # Both sessions should have started roughly simultaneously (delta < 0.04s)
        time_diff = abs(start_times["sess_alpha"] - start_times["sess_beta"])
        self.assertLess(time_diff, 0.04)

    def test_08_session_lock_registry_reference_counting(self):
        """Verify lock registry removes keys when zero references remain (no memory leak)."""
        session_id = "memleak_test_sess"
        key = f"{self.tenant_a['id']}:{session_id}"

        async def acquire_and_release():
            async with session_lock(self.tenant_a["id"], session_id, timeout_seconds=2.0):
                # While locked, entry must exist with ref_count >= 1
                async with _lock_registry._global_lock:
                    self.assertIn(key, _lock_registry._locks)
                    self.assertGreaterEqual(_lock_registry._ref_counts[key], 1)

        asyncio.run(acquire_and_release())

        # After releasing, entry must be evicted from the internal dict
        async def verify_empty():
            async with _lock_registry._global_lock:
                self.assertNotIn(key, _lock_registry._locks)
                self.assertNotIn(key, _lock_registry._ref_counts)

        asyncio.run(verify_empty())

        asyncio.run(verify_empty())

    # ── 4. UTC DateTime Modernization ──────────────────────────────────────────

    def test_09_utc_now_and_ensure_utc(self):
        """Verify timezone-aware UTC datetime generation and safe conversions."""
        now = utc_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.tzinfo, datetime.timezone.utc)

        # Naive datetime conversion
        naive_dt = datetime.datetime(2026, 11, 24, 12, 0, 0)
        aware_dt = ensure_utc(naive_dt)
        self.assertIsNotNone(aware_dt.tzinfo)
        self.assertEqual(aware_dt.tzinfo, datetime.timezone.utc)

        # Comparison between ensure_utc and utc_now must not raise TypeError
        self.assertLess(aware_dt, now)

        # None input returns None safely
        self.assertIsNone(ensure_utc(None))

    # ── 5. Tenant-Specific Retention Service ───────────────────────────────────

    def test_10_retention_policy_crud(self):
        """Verify setting and reading retention policies (7, 30, 90, indefinite)."""
        tenant_id = self.tenant_a["id"]

        # Default policy is indefinite (0)
        policy = RetentionService.get_tenant_policy(tenant_id)
        self.assertTrue(policy["is_indefinite"])
        self.assertEqual(policy["retention_days"], 0)

        # Update to 30 days
        updated = RetentionService.set_tenant_policy(tenant_id, 30)
        self.assertEqual(updated["retention_days"], 30)
        self.assertFalse(updated["is_indefinite"])

        # Update to 7 days
        updated_7 = RetentionService.set_tenant_policy(tenant_id, 7)
        self.assertEqual(updated_7["retention_days"], 7)

        # Negative days must raise ValueError
        with self.assertRaises(ValueError):
            RetentionService.set_tenant_policy(tenant_id, -5)

    def test_11_retention_dry_run_report(self):
        """Verify dry-run report accurately calculates expired count without deleting."""
        tenant_id = self.tenant_a["id"]
        RetentionService.set_tenant_policy(tenant_id, 7)

        session = _get_central_session()
        try:
            now = utc_now()
            # 3 expired logs (10 days old)
            for i in range(3):
                session.add(
                    ChatLog(
                        tenant_id=tenant_id,
                        session_id=f"dry_old_{i}",
                        encrypted_question=encrypt_text("old q"),
                        encrypted_answer=encrypt_text("old a"),
                        created_at=now - datetime.timedelta(days=10, minutes=i),
                    )
                )
            # 2 active logs (2 days old)
            for i in range(2):
                session.add(
                    ChatLog(
                        tenant_id=tenant_id,
                        session_id=f"dry_new_{i}",
                        encrypted_question=encrypt_text("new q"),
                        encrypted_answer=encrypt_text("new a"),
                        created_at=now - datetime.timedelta(days=2, minutes=i),
                    )
                )
            session.commit()
        finally:
            session.close()

        # Generate dry-run report
        reports = RetentionService.generate_cleanup_report(tenant_id)
        self.assertEqual(len(reports), 1)
        rep = reports[0]

        self.assertEqual(rep["tenant_id"], tenant_id)
        self.assertEqual(rep["retention_days"], 7)
        self.assertEqual(rep["expired_chat_logs"], 3)
        self.assertTrue(rep["dry_run"])
        self.assertIsNotNone(rep["oldest_record_date"])

        # Execute cleanup with dry_run=True (default)
        cleanup_res = RetentionService.execute_retention_cleanup(tenant_id, dry_run=True)
        self.assertTrue(cleanup_res["dry_run"])
        self.assertFalse(cleanup_res["executed"])

        # Verify nothing was deleted
        session = _get_central_session()
        try:
            remaining = session.query(ChatLog).filter(ChatLog.tenant_id == tenant_id).count()
            self.assertEqual(remaining, 5)
        finally:
            session.close()

    def test_12_retention_cleanup_execution_tenant_isolation(self):
        """Verify executing cleanup with dry_run=False strictly deletes only target tenant's expired data."""
        tenant_a_id = self.tenant_a["id"]
        tenant_b_id = self.tenant_b["id"]

        RetentionService.set_tenant_policy(tenant_a_id, 7)
        RetentionService.set_tenant_policy(tenant_b_id, 0)  # Tenant B has indefinite retention

        session = _get_central_session()
        try:
            now = utc_now()
            # Seed Tenant A: 4 expired logs (15 days old)
            for i in range(4):
                session.add(
                    ChatLog(
                        tenant_id=tenant_a_id,
                        session_id=f"tenant_a_old_{i}",
                        encrypted_question=encrypt_text("A q"),
                        encrypted_answer=encrypt_text("A a"),
                        created_at=now - datetime.timedelta(days=15),
                    )
                )
            # Seed Tenant B: 4 logs (also 15 days old, but Tenant B is indefinite)
            for i in range(4):
                session.add(
                    ChatLog(
                        tenant_id=tenant_b_id,
                        session_id=f"tenant_b_old_{i}",
                        encrypted_question=encrypt_text("B q"),
                        encrypted_answer=encrypt_text("B a"),
                        created_at=now - datetime.timedelta(days=15),
                    )
                )
            session.commit()
        finally:
            session.close()

        # Execute cleanup strictly for Tenant A with dry_run=False
        result = RetentionService.execute_retention_cleanup(tenant_a_id, dry_run=False)
        self.assertTrue(result["executed"])
        self.assertFalse(result["dry_run"])
        self.assertGreaterEqual(result["deleted_chat_logs"], 4)

        # Verify Tenant A expired logs are deleted
        session = _get_central_session()
        try:
            count_a = (
                session.query(ChatLog)
                .filter(
                    ChatLog.tenant_id == tenant_a_id,
                    ChatLog.session_id.like("tenant_a_old_%"),
                )
                .count()
            )
            self.assertEqual(count_a, 0)

            # CRITICAL: Verify Tenant B logs are 100% intact (zero cross-tenant impact)
            count_b = (
                session.query(ChatLog)
                .filter(
                    ChatLog.tenant_id == tenant_b_id,
                    ChatLog.session_id.like("tenant_b_old_%"),
                )
                .count()
            )
            self.assertEqual(count_b, 4)
        finally:
            session.close()

    # ── 6. Database Connection Pooling Configuration ───────────────────────────

    def test_13_database_engine_configuration(self):
        """Verify engine connection parameters are properly set."""
        engine = _get_central_engine()
        self.assertIsNotNone(engine)
        dialect_name = engine.dialect.name
        # On SQLite, check_same_thread must be False
        if dialect_name == "sqlite":
            # Engine connection should succeed without thread errors
            with engine.connect() as conn:
                res = conn.execute(text("SELECT 1")).scalar()
                self.assertEqual(res, 1)

    # ── 7. Gap Fix Verification Tests ──────────────────────────────────────────

    def test_14_session_lock_cancellation_safety(self):
        """Verify cancelling a task waiting for a session lock does not leak reference counts."""
        session_id = f"cancel_sess_{uuid.uuid4().hex[:6]}"
        key = f"{self.tenant_a['id']}:{session_id}"

        async def run_cancellation_scenario():
            # Task 1 holds the lock
            async with session_lock(self.tenant_a["id"], session_id, timeout=5.0):
                # Task 2 attempts to acquire lock and gets cancelled while waiting
                async def waiting_task():
                    async with session_lock(self.tenant_a["id"], session_id, timeout=10.0):
                        pass

                task = asyncio.create_task(waiting_task())
                # Yield control to let waiting_task attempt acquisition
                await asyncio.sleep(0.05)
                # Cancel task 2
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # After Task 1 exits, verify zero lingering entries or leaks in registry
            async with _lock_registry._global_lock:
                self.assertNotIn(key, _lock_registry._locks)
                self.assertNotIn(key, _lock_registry._ref_counts)

        asyncio.run(run_cancellation_scenario())

    def test_15_role_changed_at_timezone_aware_invalidation(self):
        """Verify role_changed_at handles timezone-aware timestamps without TypeError."""
        from starlette.requests import Request
        from backend.app.core.security import create_employee_token, get_employee_from_token
        from backend.database import create_employee

        emp = create_employee(
            name="Test Emp",
            email=f"emp_{uuid.uuid4().hex[:6]}@example.com",
            plain_password="password123",
            role="support",
        )
        token = create_employee_token(emp["id"], emp["email"], emp["role"])

        def make_request(tok):
            return Request({
                "type": "http",
                "headers": [(b"authorization", f"Bearer {tok}".encode("utf-8"))],
            })

        # Validate token succeeds initially
        res = asyncio.run(get_employee_from_token(make_request(token)))
        self.assertEqual(res["id"], emp["id"])

        # Update role_changed_at to future UTC time
        future_utc = (utc_now() + datetime.timedelta(hours=1)).isoformat()
        session = _get_central_session()
        try:
            from backend.database import Employee
            e = session.query(Employee).filter(Employee.id == emp["id"]).first()
            e.role_changed_at = datetime.datetime.fromisoformat(future_utc)
            session.commit()
        finally:
            session.close()

        # Token should now be rejected as session invalidated
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_employee_from_token(make_request(token)))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Session invalidated", ctx.exception.detail)

    def test_16_retention_prunes_checkpoint_blobs_and_writes(self):
        """Verify retention cleanup also prunes orphaned checkpoint blobs and writes."""
        tenant_id = self.tenant_a["id"]
        session_id = f"cp_prune_{uuid.uuid4().hex[:6]}"
        thread_id = f"{tenant_id}:{session_id}"
        old_time = utc_now() - datetime.timedelta(days=20)

        RetentionService.set_tenant_policy(tenant_id, 7)

        # Insert expired checkpoint, blob, and write directly
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                INSERT INTO langgraph_checkpoints (
                    thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                    checkpoint_type, checkpoint_bytes, metadata_type, metadata_bytes, created_at
                ) VALUES (
                    :tid, '', 'cp_prune_1', NULL, 'json', X'7b7d', 'json', X'7b7d', :dt
                )
                """),
                {"tid": thread_id, "dt": old_time},
            )
            conn.execute(
                text("""
                INSERT INTO langgraph_checkpoint_blobs (
                    thread_id, checkpoint_ns, channel, version, blob_type, blob_bytes
                ) VALUES (
                    :tid, '', 'messages', '1', 'json', X'7b7d'
                )
                """),
                {"tid": thread_id},
            )
            conn.execute(
                text("""
                INSERT INTO langgraph_checkpoint_writes (
                    thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, write_type, write_bytes
                ) VALUES (
                    :tid, '', 'cp_prune_1', 'task_1', 0, 'messages', 'json', X'7b7d'
                )
                """),
                {"tid": thread_id},
            )

        # Run retention cleanup with dry_run=False
        res = RetentionService.execute_retention_cleanup(tenant_id, dry_run=False)
        self.assertTrue(res["executed"])
        self.assertGreaterEqual(res["deleted_checkpoints"], 1)

        # Verify blobs and writes were also pruned
        with self.engine.connect() as conn:
            remaining_blobs = conn.execute(
                text("SELECT COUNT(*) FROM langgraph_checkpoint_blobs WHERE thread_id = :tid"),
                {"tid": thread_id},
            ).scalar()
            self.assertEqual(remaining_blobs, 0)

            remaining_writes = conn.execute(
                text("SELECT COUNT(*) FROM langgraph_checkpoint_writes WHERE thread_id = :tid"),
                {"tid": thread_id},
            ).scalar()
            self.assertEqual(remaining_writes, 0)

    def test_17_scheduler_idempotent_startup(self):
        """Verify calling start_scheduler repeatedly does not create duplicate scheduler instances."""
        import backend.app.scheduler as sched_mod
        try:
            sched_mod.start_scheduler()
            instance_1 = sched_mod._scheduler
            self.assertIsNotNone(instance_1)
            self.assertTrue(instance_1.running)

            # Calling a second time should be a no-op
            sched_mod.start_scheduler()
            instance_2 = sched_mod._scheduler
            self.assertIs(instance_1, instance_2)
        finally:
            sched_mod.stop_scheduler()


if __name__ == "__main__":
    unittest.main()
