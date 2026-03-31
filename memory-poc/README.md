# Memory POC — Editor Assignment with L3 Learning

Editor assignment agent that **learns from past assignments**.  
Each recommendation is saved to Postgres → next similar manuscript gets a smarter pick.

## How It Works

```mermaid
flowchart TD
    MS([📄 Manuscript]) --> F["fetch_manuscript_data()<br/>EE API"]
    F --> S["search_past_assignments()<br/>L3 READ · Postgres"]
    S --> HAS{History?}
    HAS -- Yes --> SMART["🎯 LLM recommends with context"]
    HAS -- No --> BASIC["📋 LLM recommends from scratch"]
    SMART --> SAVE["💾 save_assignment()<br/>L3 WRITE · Postgres"]
    BASIC --> SAVE
    SAVE --> DONE([✅ Next time will be smarter])

    style S fill:#3a1e5f,color:#fff
    style SAVE fill:#1b4e2d,color:#fff
```

## Learning Loop

```mermaid
sequenceDiagram
    participant Agent as Strands Agent
    participant EE as EE API
    participant PG as Postgres

    Note over Agent,PG: Assignment #1 (cold start)
    Agent->>EE: fetch_manuscript_data()
    Agent->>PG: search_past_assignments("catalysis")
    PG-->>Agent: EMPTY
    Agent-->>Agent: Recommend from rules only
    Agent->>PG: save_assignment(MS-001 → person-001)

    Note over Agent,PG: Assignment #2 (memory kicks in)
    Agent->>EE: fetch_manuscript_data()
    Agent->>PG: search_past_assignments("catalysis")
    PG-->>Agent: MS-001 → person-001 worked
    Agent-->>Agent: Better recommendation
    Agent->>PG: save_assignment(MS-002 → person-003)
```

## Files

| File | What |
|------|------|
| `memory.py` | L3 store: save, search, format for prompt |
| `agent.py` | Strands agent with 2 tools + mock mode |
| `app.py` | FastAPI: `/execute_workflow`, `/health` |
| `tests/test_memory.py` | 12 tests, no Docker/AWS needed |

## Run Tests

```bash
cd memory-poc
pytest tests/ -v
```

## Memory Tiers

| Tier | What | Backend |
|------|------|---------|
| L2 | Session checkpoint (crash recovery) | MemorySaver / S3 |
| L3 | Past assignments (learning) | Postgres |

## What L3 Stores

```json
{
  "editor_person_id": "person-001",
  "reasoning": "Expert in catalysis, lowest rank, no COI",
  "runner_up": "person-002",
  "journal_id": "JACS",
  "manuscript_number": "MS-001",
  "timestamp": "2026-03-31T10:00:00Z"
}
```

