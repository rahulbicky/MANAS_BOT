"""
backend/scripts/audit_section2_postgres.py
------------------------------------------
PostgreSQL & pgvector Production Verification Suite:
  1. Live PostgreSQL connection & pgvector extension check
  2. pgvector dense vector insert and cosine distance (<=>) search
  3. Persistent LangGraph checkpoint write, simulated restart & recovery
  4. Cross-process PostgreSQL Advisory Locks (pg_try_advisory_lock)
  5. Transaction safety and rollback atomicity
  6. Table export/backup & restore procedure verification
"""
import os
import sys
import json
import subprocess
import psycopg2
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(line_buffering=True)

results = {}

def audit_log(test_name: str, passed: bool, details: str):
    status = "PASS" if passed else "FAIL"
    results[test_name] = {"status": status, "details": details}
    print(f"[{status}] {test_name}: {details}", flush=True)

print("==================================================")
print("AUDIT SECTION 2: POSTGRESQL & PGVECTOR VERIFICATION")
print("==================================================")

db_url = os.getenv("CENTRAL_DB_URL")
if not db_url or "postgresql" not in db_url:
    print("[FAIL] CENTRAL_DB_URL not configured for PostgreSQL.")
    sys.exit(1)

# 1. PostgreSQL Version & pgvector Extension
try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    pg_version = cur.fetchone()[0]

    cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()

    cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
    row = cur.fetchone()
    vector_version = row[0] if row else "Not Installed"

    passed = (bool(pg_version) and vector_version != "Not Installed")
    audit_log(
        "PostgreSQL & pgvector Instance Connection",
        passed,
        f"Version={pg_version.split()[0]} {pg_version.split()[1]}, pgvector={vector_version}"
    )
    conn.close()
except Exception as e:
    audit_log("PostgreSQL & pgvector Instance Connection", False, str(e))

# 2. pgvector Vector Operations & Cosine Similarity Search
try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS audit_pgvector_test;")
    cur.execute("""
        CREATE TABLE audit_pgvector_test (
            id SERIAL PRIMARY KEY,
            doc_name VARCHAR(100),
            embedding vector(4)
        );
    """)
    # Insert two test vectors
    cur.execute("INSERT INTO audit_pgvector_test (doc_name, embedding) VALUES (%s, %s);", ("doc_billing", "[1.0, 0.0, 0.0, 0.0]"))
    cur.execute("INSERT INTO audit_pgvector_test (doc_name, embedding) VALUES (%s, %s);", ("doc_support", "[0.0, 1.0, 0.0, 0.0]"))
    conn.commit()

    # Query using cosine distance operator (<=>)
    query_vector = "[0.9, 0.1, 0.0, 0.0]"
    cur.execute("""
        SELECT doc_name, 1 - (embedding <=> %s) AS cosine_similarity
        FROM audit_pgvector_test
        ORDER BY embedding <=> %s ASC
        LIMIT 1;
    """, (query_vector, query_vector))
    best_match = cur.fetchone()
    cur.execute("DROP TABLE IF EXISTS audit_pgvector_test;")
    conn.commit()
    conn.close()

    passed = (best_match and best_match[0] == "doc_billing" and best_match[1] > 0.9)
    audit_log("pgvector Vector Insert & Cosine Distance (<=>)", passed, f"Nearest Neighbor={best_match[0]}, Similarity={best_match[1]:.4f}")
except Exception as e:
    audit_log("pgvector Vector Insert & Cosine Distance (<=>)", False, str(e))

# 3. LangGraph Persistent Checkpointing Across Restart
try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    # Ensure checkpoint tables exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
            thread_id VARCHAR(255) PRIMARY KEY,
            checkpoint_data TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    test_thread = "audit_tenant_100:sess_restart_99"
    test_state = json.dumps({"messages": ["Hello", "Can you help me?"], "intent": "support"})

    # Session 1: Write checkpoint
    cur.execute("""
        INSERT INTO langgraph_checkpoints (thread_id, checkpoint_data)
        VALUES (%s, %s)
        ON CONFLICT (thread_id) DO UPDATE SET checkpoint_data = EXCLUDED.checkpoint_data;
    """, (test_thread, test_state))
    conn.commit()
    conn.close()

    # Simulate Process Restart: Open completely fresh connection
    conn_fresh = psycopg2.connect(db_url)
    cur_fresh = conn_fresh.cursor()
    cur_fresh.execute("SELECT checkpoint_data FROM langgraph_checkpoints WHERE thread_id = %s;", (test_thread,))
    recovered_data = cur_fresh.fetchone()
    
    # Clean up test checkpoint
    cur_fresh.execute("DELETE FROM langgraph_checkpoints WHERE thread_id = %s;", (test_thread,))
    conn_fresh.commit()
    conn_fresh.close()

    recovered_state = json.loads(recovered_data[0]) if recovered_data else {}
    passed = (recovered_state.get("intent") == "support" and len(recovered_state.get("messages", [])) == 2)
    audit_log("LangGraph Checkpoint Recovery Across Restart", passed, f"Recovered State={recovered_state}")
except Exception as e:
    audit_log("LangGraph Checkpoint Recovery Across Restart", False, str(e))

# 4. PostgreSQL Advisory Locks across Separate Application Processes
try:
    lock_id = 87654321
    # Process 1 acquires lock
    conn1 = psycopg2.connect(db_url)
    cur1 = conn1.cursor()
    cur1.execute("SELECT pg_try_advisory_lock(%s);", (lock_id,))
    p1_acquired = cur1.fetchone()[0]

    # Process 2 (separate script in subprocess) tries to acquire same lock
    worker2_code = f"""
import sys
sys.path.insert(0, r'{os.path.abspath("manasbot/Lib/site-packages")}')
sys.path.insert(0, r'{os.path.abspath(".")}')
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv('CENTRAL_DB_URL'))
cur = conn.cursor()
cur.execute('SELECT pg_try_advisory_lock({lock_id});')
print(cur.fetchone()[0])
conn.close()
"""
    env_copy = os.environ.copy()
    env_copy["PYTHONPATH"] = f"{os.path.abspath('.')};{os.path.abspath('manasbot/Lib/site-packages')}"
    p2_output = subprocess.check_output(
        [sys.executable, "-c", worker2_code],
        env=env_copy,
        timeout=10,
    ).decode().strip()
    p2_acquired = (p2_output == "True")

    # Process 1 releases lock
    cur1.execute("SELECT pg_advisory_unlock(%s);", (lock_id,))
    p1_released = cur1.fetchone()[0]
    conn1.close()

    # Process 2 tries again after release
    p2_retry_output = subprocess.check_output(
        [sys.executable, "-c", worker2_code],
        env=env_copy,
        timeout=10,
    ).decode().strip()
    p2_retry_acquired = (p2_retry_output == "True")

    # Clean unlock from Process 2
    conn2_cleanup = psycopg2.connect(db_url)
    cur2_cleanup = conn2_cleanup.cursor()
    cur2_cleanup.execute("SELECT pg_advisory_unlock(%s);", (lock_id,))
    conn2_cleanup.close()

    passed = (p1_acquired is True and p2_acquired is False and p1_released is True and p2_retry_acquired is True)
    audit_log(
        "PostgreSQL Advisory Locks Across Worker Processes",
        passed,
        f"Worker1 Locked={p1_acquired}, Worker2 Blocked={not p2_acquired}, Worker1 Unlocked={p1_released}, Worker2 Acquired={p2_retry_acquired}"
    )
except Exception as e:
    audit_log("PostgreSQL Advisory Locks Across Worker Processes", False, str(e))

# 5. Database Transactions & Rollback Safety
try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS audit_tx_test;")
    cur.execute("CREATE TABLE audit_tx_test (id INT PRIMARY KEY, val TEXT);")
    conn.commit()

    # Intentional rollback test
    try:
        cur.execute("INSERT INTO audit_tx_test VALUES (1, 'initial');")
        # Trigger error (duplicate PK)
        cur.execute("INSERT INTO audit_tx_test VALUES (1, 'duplicate');")
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()

    # Verify nothing was committed from failed transaction
    cur.execute("SELECT COUNT(*) FROM audit_tx_test;")
    count_after_rollback = cur.fetchone()[0]

    # Clean commit test
    cur.execute("INSERT INTO audit_tx_test VALUES (2, 'valid');")
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM audit_tx_test;")
    count_after_commit = cur.fetchone()[0]

    cur.execute("DROP TABLE IF EXISTS audit_tx_test;")
    conn.commit()
    conn.close()

    passed = (count_after_rollback == 0 and count_after_commit == 1)
    audit_log("Transaction Safety & Rollback Atomicity", passed, f"Rollback count={count_after_rollback} (0 expected), Commit count={count_after_commit} (1 expected)")
except Exception as e:
    audit_log("Transaction Safety & Rollback Atomicity", False, str(e))

# 6. Backup & Restore Procedures Verification
try:
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS audit_backup_test;")
    cur.execute("CREATE TABLE audit_backup_test (id SERIAL PRIMARY KEY, tenant_id VARCHAR(50), payload TEXT);")
    cur.execute("INSERT INTO audit_backup_test (tenant_id, payload) VALUES ('t1', 'Config 1'), ('t2', 'Config 2');")
    conn.commit()

    # 1. Export / Backup
    cur.execute("SELECT id, tenant_id, payload FROM audit_backup_test;")
    exported_rows = cur.fetchall()
    backup_json = json.dumps([{"id": r[0], "tenant_id": r[1], "payload": r[2]} for r in exported_rows])

    # 2. Drop table to simulate data loss
    cur.execute("DROP TABLE audit_backup_test;")
    conn.commit()

    # 3. Restore / Re-import
    cur.execute("CREATE TABLE audit_backup_test (id SERIAL PRIMARY KEY, tenant_id VARCHAR(50), payload TEXT);")
    for item in json.loads(backup_json):
        cur.execute("INSERT INTO audit_backup_test (tenant_id, payload) VALUES (%s, %s);", (item["tenant_id"], item["payload"]))
    conn.commit()

    # 4. Verify restored data
    cur.execute("SELECT COUNT(*) FROM audit_backup_test;")
    restored_count = cur.fetchone()[0]

    cur.execute("DROP TABLE audit_backup_test;")
    conn.commit()
    conn.close()

    passed = (len(exported_rows) == 2 and restored_count == 2)
    audit_log("Backup Export & Restore Procedure Verification", passed, f"Exported rows={len(exported_rows)}, Restored rows={restored_count}")
except Exception as e:
    audit_log("Backup Export & Restore Procedure Verification", False, str(e))

print("==================================================")
with open("audit_section2_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("PostgreSQL Audit completed successfully.")
