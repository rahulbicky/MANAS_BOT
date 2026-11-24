# ManasBot — Agentic AI Architecture

## 1. Overview

ManasBot implements Agentic AI workflows through LangChain and LangGraph stateful execution graphs.
Rather than relying on brittle one-shot prompts, ManasBot equips the LLM with structured, tenant-isolated tools to perform retrieval, profile inspection, lead capture, and incident ticketing.

---

## 2. Agentic Tool Suite (`backend/rag/tools.py`)

All agentic tools enforce:
1. **Strict Pydantic Input Schemas**: Every parameter is typed, bounded, and validated.
2. **Tenant Data Isolation**: Tools require `tenant_id` and run queries bound exclusively to that tenant's database partition.
3. **Execution Timeouts**: Async operations are wrapped with strict timeout limits (5.0s – 8.0s).
4. **Structured Result Protocol**: Tools return standardized `ToolExecutionResult(success, tool_name, tenant_id, data, error, latency_ms)`.
5. **Zero Long-Lived DB Locks**: Database sessions are opened only for the duration of the SQL operation and closed immediately.

### Available Tools:

| Tool Name | Class / Function | Purpose | Input Schema |
|---|---|---|---|
| `knowledge_retrieval` | `execute_knowledge_retrieval` | Semantic vector search over tenant documents | `query` (str), `top_k` (int) |
| `business_profile` | `execute_business_profile` | Company hours, contact email, phone, location | `tenant_id` (pre-bound) |
| `lead_capture` | `execute_lead_capture` | Stores customer name, phone, email, and inquiry | `name`, `raw_message`, `phone`, `email` |
| `support_incident` | `execute_support_incident` | Logs support ticket or operational issue | `title`, `description`, `category`, `severity` |

---

## 3. LangChain Structured Tool Factory

To prevent LLM agents from leaking or accessing other tenants' data, `get_tenant_agent_tools(tenant_id)` binds the tenant identifier at tool construction time:

```python
from backend.rag.tools import get_tenant_agent_tools

# Returns tools pre-bound to 'tenant_acme'
tools = get_tenant_agent_tools(tenant_id="tenant_acme")
```

The LLM cannot alter the `tenant_id` parameter because it is encapsulated in the tool's closure.

---

## 4. Multi-Turn Conversational Graph

LangGraph manages the multi-turn conversational workflow across 6 coordinated nodes:

```
[START]
   │
   ▼
[guard_and_intent_node]
   │
   ├── (Pure lead detected) ───────────► [lead_capture_node] ──┐
   │                                                           │
   └── (Inquiry / Question) ───────────► [faq_matcher_node]    │
                                                │              │
                                                ▼              │
                                       [rag_retriever_node]    │
                                                │              │
                                                ▼              │
                                     [answer_generation_node]  │
                                                │              │
                                                ▼              │
                                    [citation_formatter_node] ◄┘
                                                │
                                                ▼
                                              [END]
```

### Persistent Checkpointing:
- Persistent thread checkpoints are saved using `AsyncPostgresSaver` with composite thread keys: `{tenant_id}:{session_id}`.
- If PostgreSQL is temporarily unreachable, checkpointer falls back gracefully to `MemorySaver` without dropping requests.
