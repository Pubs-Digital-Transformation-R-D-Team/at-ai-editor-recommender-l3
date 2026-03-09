# AWS Strands Agents SDK — Memory Migration Analysis

**Current Stack**: LangGraph + `AsyncPostgresSaver` + `AsyncPostgresStore` + PostgreSQL on RDS  
**Target Stack**: AWS Strands Agents SDK  
**Analysis Date**: March 2026  
**Purpose**: Evaluate what it takes to replace the LangGraph memory implementation with Strands

---

## 1. Executive Summary

| Dimension | Verdict |
|---|---|
| **Is migration feasible?** | Yes, partially |
| **Tier 2 (Session/Crash Recovery)** | Strands has `S3SessionManager` / custom `RepositorySessionManager` — but different semantics |
| **Tier 3 (Long-term / Learning Loop)** | Strands has `AgentCoreMemorySessionManager` (community) — matches intent well |
| **Architecture paradigm shift** | High — LangGraph is graph-based; Strands is model-driven agent loop |
| **Code reuse of memory.py** | 60–70% reusable (save/search/format functions stay the same) |
| **Risk** | Medium — no per-node checkpointing in Strands = different crash recovery model |
| **Recommendation** | **Hybrid approach**: Convert agent execution to Strands; keep Postgres store for Tier 3 via custom `SessionRepository` |

---

## 2. What We Built with LangGraph

### Tier 2 — Session Memory (`AsyncPostgresSaver`)

```
LangGraph Graph executes:
  Node 1: fetch_manuscript_data       → checkpoint saved to Postgres
  Node 2: generate_recommendation     → checkpoint saved to Postgres  ← pod crash here
  Node 3: verify_recommendation       (never executed)
  
Pod restarts → loads checkpoint from Postgres → resumes at Node 3
```

**Tables created**: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`  
**Code**: `create_checkpointer()` in `memory.py` — `AsyncConnectionPool` + `AsyncPostgresSaver`  
**Used in**: `EditorAssignmentWorkflow.__init__()` — passed as `checkpointer=` to `workflow_builder.compile()`

### Tier 3 — Long-term Memory (`AsyncPostgresStore`)

```
Workflow completes → save_assignment_to_memory() → stores to Postgres:
  namespace: ("assignments", "jm")
  key:       "jm-2021-018697"
  value:     {editor_id, reasoning, topics, timestamp, runner_up, ...}

Next workflow → search_similar_assignments() → inject {past_assignments} into LLM prompt
```

**Tables created**: `store`, `store_migrations`  
**Code**: `create_store()`, `save_assignment_to_memory()`, `search_similar_assignments()`, `format_past_assignments_for_prompt()` in `memory.py`  
**Evidence it works**: Feb 24 (save) → Feb 26 (search returned 1 result → injected into prompt)

---

## 3. Strands Architecture — Key Concepts

Strands is fundamentally different from LangGraph:

| Concept | LangGraph | Strands |
|---|---|---|
| **Execution model** | Explicit graph with nodes and edges | Model-driven agent loop — LLM decides what tool to call |
| **Control flow** | You define: A → B → C (or conditional branches) | LLM autonomously picks tools until task complete |
| **State** | `TypedDict` passed between graph nodes | `agent.messages` (conversation) + `agent.state` (key-value) |
| **Memory hooks** | Checkpointer auto-saves after each node | Session manager auto-saves after each invocation |
| **Tools** | Python functions registered on graph | `@tool` decorated functions; LLM decides when to call them |
| **Bedrock** | `AsyncAnthropicBedrock` client | `BedrockModel(model_id=...)` — native Bedrock integration |
| **Resume after crash** | Per-node checkpoint → resume from exact node | Per-invocation session snapshot → re-run from last full message |

---

## 4. Component-by-Component Mapping

### 4.1. Tier 2 — Session / Crash Recovery

#### Current (LangGraph)

```python
# memory.py
async def create_checkpointer():
    pool = AsyncConnectionPool(conninfo=uri, max_size=5, open=False)
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    return checkpointer

# ee_graph_anthropic.py
graph = workflow_builder.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": "jm-2021-018697"}}
result = await graph.ainvoke(state, config)
```

**What it gives**: After every single graph node, state is checkpointed. If pod dies mid-node-2, next run resumes from node-3 automatically.

#### Strands Equivalent

Strands saves session state **after each full agent invocation** (not per-node). Options:

**Option A: `S3SessionManager` (Built-in)**
```python
from strands import Agent
from strands.session.s3_session_manager import S3SessionManager

session_manager = S3SessionManager(
    session_id=f"manuscript-{manuscript_number}",
    bucket="acs-er-agent-sessions",
    prefix="dev/",
    region_name="us-east-1"
)
agent = Agent(
    model=BedrockModel(model_id="us.amazon.nova-premier-v1:0"),
    session_manager=session_manager,
    tools=[fetch_manuscript_data, generate_recommendation, verify_recommendation]
)
result = agent(f"Assign an editor to manuscript {manuscript_number}")
```

- Saves conversation + state to S3 after each invocation
- On restart, agent reloads session → LLM re-executes from recovered context
- **Gap**: No per-node granularity. If pod dies mid-LLM-call, whole invocation retries (not resumes from middle of tool call chain)
- **Requires**: S3 bucket, IAM permissions (`s3:PutObject`, `s3:GetObject`, `s3:ListBucket`)

**Option B: Custom `RepositorySessionManager` → Postgres backend (Recommended)**
```python
from strands.session.repository_session_manager import RepositorySessionManager
from strands.session.session_repository import SessionRepository
from strands.types.session import Session, SessionAgent, SessionMessage

class PostgresSessionRepository(SessionRepository):
    """Custom Strands session repository backed by your existing RDS Postgres."""

    def __init__(self, pool):
        self.pool = pool  # Re-use your existing AsyncConnectionPool

    def create_session(self, session: Session) -> Session: ...
    def read_session(self, session_id: str) -> Optional[Session]: ...
    def update_session(self, session: Session) -> Session: ...
    def create_agent(self, session_id: str, agent: SessionAgent) -> SessionAgent: ...
    def read_agent(self, session_id: str, agent_id: str) -> Optional[SessionAgent]: ...
    def update_agent(self, session_id: str, agent: SessionAgent) -> SessionAgent: ...
    def create_message(self, session_id: str, agent_id: str, message: SessionMessage) -> SessionMessage: ...
    def read_message(self, session_id: str, agent_id: str, message_id: str) -> Optional[SessionMessage]: ...
    def update_message(self, session_id: str, agent_id: str, message: SessionMessage) -> SessionMessage: ...
    def list_messages(self, session_id: str, agent_id: str) -> list[SessionMessage]: ...

pg_repo = PostgresSessionRepository(pool=your_existing_pool)
session_manager = RepositorySessionManager(
    session_id=manuscript_number,
    session_repository=pg_repo
)
agent = Agent(session_manager=session_manager)
```

- Keeps data in your existing RDS Postgres (same database, new schema/tables)
- Requires implementing 10 CRUD methods against new `strands_sessions` tables
- **Trade-off**: More work upfront, but keeps all data in one place (no new S3 bucket needed)

**Key difference vs LangGraph checkpointing**:

| LangGraph | Strands |
|---|---|
| Saves after EACH NODE (6 checkpoints per workflow) | Saves after EACH INVOCATION (1 snapshot per run) |
| Can resume from middle of a workflow | Can re-run from start with saved context |
| 4 Postgres tables with binary blob storage | JSON-based session/agent/message rows |
| `thread_id` = workflow run | `session_id` = conversation session |

> **Impact for Editor Recommender**: Our workflow runs once and completes in ~30s. Pod-crash-mid-node is possible but rare. Strands' per-invocation approach is sufficient for this use case; the per-node granularity of LangGraph is overengineered for a 30-second single-shot workflow.

---

### 4.2. Tier 3 — Long-term Memory (Learning Loop)

#### Current (LangGraph)

```python
# memory.py
async def save_assignment_to_memory(store, state: dict) -> None:
    await store.aput(
        namespace=("assignments", journal_id),
        key=manuscript_number,
        value={...editor_id, reasoning, topics, timestamp...}
    )

async def search_similar_assignments(store, query, journal_id, limit=5) -> list:
    results = await store.asearch(("assignments", journal_id), query=query, limit=limit)
    return results

# ee_graph_anthropic.py — in _generate_editor_recommendation()
past = await search_similar_assignments(self._store, query, journal_id)
past_text = format_past_assignments_for_prompt(past)
# Injects past_text into {past_assignments} in the prompt
```

**Data proven live**: `store` table has 5 rows; Feb 26 run confirmed "1 result found → injected into prompt".

#### Strands Equivalent

**Option A: Amazon AgentCore Memory (Community Third-Party)**
```python
# Install: pip install strands-agents-agentcore-memory
from strands_agentcore_memory import AgentCoreMemorySessionManager

session_manager = AgentCoreMemorySessionManager(
    memory_id="er-long-term-memory",   # AgentCore Memory resource ID
    session_id=manuscript_number,
    # Supports short-term memory (STM) and long-term memory (LTM)
    # Strategies: user preferences, facts, session summaries
)
agent = Agent(session_manager=session_manager)
```

- AWS managed memory service on top of Bedrock
- **Advantages**: Intelligent retrieval (semantic search built-in), manages TTL, scales automatically
- **Disadvantages**: Requires setting up Amazon Bedrock AgentCore Memory resource; adds AWS cost; new infrastructure; data leaves your RDS control
- **Requires**: Bedrock AgentCore enabled in your AWS account (412381768680), appropriate IAM policies

**Option B: Keep `AsyncPostgresStore` as a direct call from Strands tools (Recommended for POC)**
```python
# memory.py — unchanged! Same save/search functions work.

from strands import Agent, tool, ToolContext

@tool(context=True)
async def search_past_assignments(query: str, journal_id: str, tool_context: ToolContext) -> str:
    """Search long-term memory for past editor assignments similar to this manuscript."""
    store = tool_context.agent.state.get("store")  # injected via agent.state
    results = await search_similar_assignments(store, query, journal_id)
    return format_past_assignments_for_prompt(results)

# In app.py lifespan:
agent = Agent(
    model=BedrockModel(model_id="us.amazon.nova-premier-v1:0"),
    tools=[search_past_assignments, ...],
    state={"store": store}  # Inject Postgres store into agent state
)
```

- **Zero change** to `memory.py` save/search/format logic
- Wraps existing functions as Strands `@tool` decorated functions
- The LLM naturally calls `search_past_assignments` when processing a manuscript (model-driven)
- `save_assignment_to_memory()` called after agent invocation completes (same timing as now, from app.py/hooks)
- **Advantages**: No new infrastructure, existing RDS data preserved, 0% data migration
- **Disadvantages**: LLM decides when to call search (may need good system prompt guidance)

---

### 4.3. `EditorAssignmentWorkflow` → Strands `Agent`

#### Current (LangGraph)

```python
# ee_graph_anthropic.py — 472 lines
class EditorAssignmentWorkflow:
    def _build_graph(self):
        builder = StateGraph(State)
        builder.add_node("fetch_manuscript_data", self._fetch_manuscript_data)
        builder.add_node("generate_editor_recommendation", self._generate_editor_recommendation)
        builder.add_node("verify_recommendation", self._verify_recommendation)
        builder.add_node("call_assign_api", self._call_assign_api)
        builder.add_edge(START, "fetch_manuscript_data")
        builder.add_edge("fetch_manuscript_data", "generate_editor_recommendation")
        builder.add_edge("generate_editor_recommendation", "verify_recommendation")
        builder.add_conditional_edges("verify_recommendation", ...)
        return builder.compile(checkpointer=self._checkpointer)

    async def run(self, manuscript_number, journal_id, ...):
        config = {"configurable": {"thread_id": manuscript_number}}
        result = await self._graph.ainvoke(initial_state, config)
```

#### Strands Equivalent

```python
# ee_agent_strands.py — proposed
from strands import Agent
from strands.models import BedrockModel
from strands.session.s3_session_manager import S3SessionManager

class EditorAssignmentAgent:

    def __init__(self, store=None, model_id="us.amazon.nova-premier-v1:0"):
        self._store = store
        self._model = BedrockModel(model_id=model_id, region_name="us-east-1")

    async def run(self, manuscript_number: str, journal_id: str) -> dict:
        session_manager = S3SessionManager(
            session_id=manuscript_number,
            bucket="acs-er-agent-sessions",
            region_name="us-east-1"
        )
        agent = Agent(
            model=self._model,
            system_prompt=self._build_system_prompt(journal_id),
            tools=[
                fetch_manuscript_data,        # @tool decorated
                generate_editor_recommendation, # @tool decorated
                verify_and_assign,            # @tool decorated
            ],
            session_manager=session_manager,
            state={"store": self._store, "journal_id": journal_id}
        )
        result = await agent.invoke_async(
            f"Process manuscript {manuscript_number} for journal {journal_id}. "
            f"Fetch the data, recommend an editor, verify, and assign."
        )
        # Save to long-term memory after completion
        await save_assignment_to_memory(self._store, extract_state_from_result(result))
        return result
```

**Important note**: In Strands, the LLM reads the task and decides which tools to call and in what order. You guide it through the system prompt rather than wiring explicit edges. This is a fundamentally different mental model.

---

## 5. Gap Analysis

| Feature | LangGraph (Current) | Strands | Gap |
|---|---|---|---|
| **Postgres checkpointing** | ✅ `AsyncPostgresSaver` (native) | ❌ No built-in | Must build custom `SessionRepository` |
| **Per-node state save** | ✅ Automatic after each node | ❌ Per-invocation only | Different recovery granularity |
| **Long-term store** | ✅ `AsyncPostgresStore` (native) | ❌ No native Postgres store | Keep existing or wrap as tool |
| **Semantic search (pgvector)** | ✅ `asearch()` (when enabled) | Via AgentCore (managed) | Either path requires pgvector setup |
| **Bedrock integration** | Via `AsyncAnthropicBedrock` | ✅ `BedrockModel` (native) | Cleaner in Strands |
| **Explicit workflow control** | ✅ Graph nodes + edges | ❌ Model-driven only | System prompt must be very precise |
| **Conditional branching** | ✅ `add_conditional_edges()` | Via model reasoning + tools | Less deterministic in Strands |
| **Existing RDS data** | ✅ All data lives here | Not natively connected | Need custom repo or keep Postgres calls |
| **EKS deployment** | ✅ Already deployed | ✅ Native EKS support | No change needed |
| **Audit trail / Replay** | ✅ Full checkpoint history in DB | Partial (session snapshots) | LangGraph is better for audit |
| **IRSA / Bedrock auth** | ✅ Working (IRSA) | ✅ Same (uses boto3) | No change |

---

## 6. Files Impacted by Migration

### Files that change significantly

| File | Current Role | Strands Migration |
|---|---|---|
| `ee_graph_anthropic.py` (472 lines) | LangGraph graph with nodes/edges | Replace with `Agent` + `@tool` functions |
| `app.py` (220 lines) | Creates checkpointer + store + workflow | Remove `create_checkpointer()`; keep `create_store()` |
| `memory.py` (367 lines) | Core memory module | `create_checkpointer()` removed; `create_store()` kept; add `SessionRepository` implementation |

### Files that stay the same

| File | Reason |
|---|---|
| `memory.py` → `save_assignment_to_memory()` | Logic unchanged, called from new agent code |
| `memory.py` → `search_similar_assignments()` | Called from a `@tool` wrapper |
| `memory.py` → `format_past_assignments_for_prompt()` | Used same way |
| `prompts.py` | System prompt content reusable; `{past_assignments}` injection pattern stays |
| `ee_api_adapter.py` | EE API calls unchanged |
| `client.py`, `client_api.py` | FastAPI request handling unchanged |
| `k8s/` deployment manifests | Same EKS cluster, IRSA, namespace `er` |
| PostgreSQL `store` + `store_migrations` tables | Still used for Tier 3 |

---

## 7. What Would NOT Work with Strands (By Design)

1. **Per-node state granularity**: Strands does not checkpoint after every tool call — only after the full agent invocation completes. The LangGraph 4-table checkpoint schema (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`) has no equivalent.

2. **Deterministic node ordering**: LangGraph guarantees nodes execute in your defined order (graph edges). Strands lets the LLM choose what to call next. For strict business workflows (fetch → recommend → verify → assign), you must use detailed system prompts or multi-agent Graph patterns instead.

3. **Native `AsyncPostgresStore` integration**: Strands has no concept of a LangGraph-style `Store`. Long-term memory must come from the Strands `AgentCore Memory` third-party integration or be wired in manually via `@tool` + `ToolContext`.

---

## 8. Recommended Migration Strategy

### Phase 1: Hybrid (Minimal Risk — 1–2 weeks)

Keep the existing Tier 3 memory (Postgres store), replace only the LangGraph execution engine:

```
Current:                                 After Phase 1:
─────────────────────────────────        ──────────────────────────────────
FastAPI app.py                           FastAPI app.py
  → create_checkpointer()      DROP        → create_store() (keep)
  → create_store()             KEEP        → S3SessionManager (add)
  → EditorAssignmentWorkflow   REPLACE     → EditorAssignmentAgent (new Strands)
    (LangGraph graph)                        (@tool decorated functions)
  → memory.py Tier 2          REPLACE     → memory.py Tier 3 only (keep)
  → memory.py Tier 3          KEEP
```

**Session memory**: S3SessionManager (conversation + state snapshot per manuscript run)  
**Long-term memory**: same Postgres store, called from `@tool search_past_assignments`  
**DB impact**: `checkpoint_*` tables go dormant; `store` table continues growing  

### Phase 2: Full AWS-Native (Optional — longer term)

If the team wants a fully managed stack:

```
S3SessionManager         → Amazon AgentCore Memory (STM)
AsyncPostgresStore        → Amazon AgentCore Memory (LTM with semantic search)
Custom @tool logic        → AgentCore Memory native retrieval
```

**Requires**: Bedrock AgentCore enabled in AWS account 412381768680, new IAM policies, data migration from `store` table.

---

## 9. New Dependencies for Phase 1

```toml
# pyproject.toml additions
strands-agents = ">=1.29.0"
strands-agents-tools = ">=0.1.0"   # built-in tools (optional)
boto3 = ">=1.35.0"                 # already used for Bedrock — verify version

# Remove (optional — can keep for backward compatibility during transition)
langgraph = "*"
langgraph-checkpoint-postgres = "*"
```

**New IAM permissions for S3SessionManager** (IRSA policy update needed):
```json
{
  "Effect": "Allow",
  "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::acs-er-agent-sessions",
    "arn:aws:s3:::acs-er-agent-sessions/*"
  ]
}
```

---

## 10. Decision Summary

| Question | Answer |
|---|---|
| Do we lose the learning loop? | **No** — Tier 3 Postgres store is preserved unchanged |
| Do we lose the 5 existing store records? | **No** — same DB, same tables |
| Do we lose crash recovery? | **Partially** — Strands resumes at invocation level, not node level |
| Will the Feb 24 → Feb 26 learning loop pattern still work? | **Yes** — save and search functions are unchanged |
| Is this a big rewrite? | **Medium** — `ee_graph_anthropic.py` rewrites as Strands agent tools; `memory.py` loses Tier 2 but Tier 3 stays |
| Biggest risk? | LLM-driven control flow is less predictable than explicit graph edges — needs strong system prompt engineering |
| Best first step? | Create `ee_agent_strands.py` alongside existing `ee_graph_anthropic.py` and A/B test both |
