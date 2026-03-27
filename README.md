# at-ai-editor-recommender-l3

L3 multi-agent POC for automated peer-review editor assignment.  
Two AI agents collaborate via the **A2A protocol** with **Human-in-the-Loop** oversight.

---

## Architecture

```
                        ┌─────────────────────────────┐
                        │   LangGraph Service :8000    │
                        │                             │
  Manuscript ──────────►│  ReAct Agent (Nova Premier) │
  + Editors             │  • Orchestrates workflow     │
                        │  • Calls COI check tool      │
                        │  • Serves editor history     │
                        │  • HITL interrupt/resume     │
                        └────────────┬────────────────┘
                                     │  A2A POST /tasks/send
                                     ▼
                        ┌─────────────────────────────┐
                        │   Strands COI Service :8001  │
                        │                             │
                        │  COI Agent (Nova Premier)   │
                        │  • Checks conflict of        │
                        │    interest per editor       │
                        │  • Calls back to :8000 for   │
                        │    each editor's history     │
                        └─────────────────────────────┘
```

Both agents use **AWS Bedrock** (`us.amazon.nova-premier-v1:0`, `us-east-1`) via IRSA.

---

## Services

| Service | Port | Image |
|---------|------|-------|
| LangGraph orchestrator | 8000 | `ghcr.io/acspubsedsg/at-ai-editor-recommender-langgraph` |
| Strands COI checker | 8001 | `ghcr.io/acspubsedsg/at-ai-editor-recommender-strands-coi` |

---

## Quick Start (local, mock mode — no Bedrock needed)

```bash
# Terminal 1 — Strands COI service
cd at-ai-editor-recommender-l3
PYTHONPATH=. MOCK_COI=true python strands_service/server.py

# Terminal 2 — LangGraph service
PYTHONPATH=. MOCK_REACT=true python langgraph_service/callback_server.py

# Terminal 3 — Streamlit UI
streamlit run streamlit_app.py --server.port 8501
```

Or use the one-click launcher (PowerShell):
```powershell
.\start.ps1
```

A2A Agent Cards:
- http://localhost:8000/.well-known/agent.json — LangGraph
- http://localhost:8001/.well-known/agent.json — Strands COI

---

## Mock vs Live Mode

| Env var | Effect |
|---------|--------|
| `MOCK_COI=true` | Strands bypasses Bedrock, uses rule-based conflict detection |
| `MOCK_REACT=true` | LangGraph bypasses Bedrock, uses deterministic mock workflow |
| *(both unset)* | Both agents use Nova Premier via AWS Bedrock |

A2A calls between services are **always real HTTP** regardless of mock mode.

---

## Composite Scoring & HITL

Each candidate editor is scored across **5 dimensions** (weighted):

| Dimension | Weight | Source |
|-----------|--------|--------|
| Topic match | 30% | Keyword overlap with manuscript |
| Capacity | 20% | Current workload vs max |
| COI status | 20% | Flagged = 0, Approved = 100 |
| Track record | 15% | Acceptance rate, avg review time |
| Turnaround | 15% | Days to first decision |

**HITL decision modes** (based on score gap between #1 and #2):

| Mode | Condition | Behaviour |
|------|-----------|----------|
| `auto_assign` | Gap > 20 and no COI flags | System auto-assigns top editor |
| `soft_review` | Gap 10–20 | Suggested pick, human confirms |
| `full_hitl` | Gap < 10 or any COI flag | Human must choose |

---

## Tests

Run the full suite (145 tests, ~4 s):

```bash
pytest
```

Run a specific file:
```bash
pytest tests/test_scoring.py -v
```

| Test file | Tests | Coverage |
|-----------|-------|----------|
| `test_callback_server.py` | 41 | Routes, A2A handler, agent card, editor utils, backward-compat imports |
| `test_coi_agent.py` | 22 | JSON extraction, mock COI, system prompt, Strands agent card, health |
| `test_scoring.py` | 38 | All 5 scoring dimensions, HITL thresholds, edge cases |
| `test_fake_data.py` | 17 | Data integrity, manuscript/editor structure |
| `test_streamlit_app.py` | 13 | UI helper functions |

---

## Live Bedrock (IRSA)

The SSO role has an explicit deny on `bedrock:InvokeModel`.  
Use the IRSA token from the running ER pod:

```powershell
# Extract token from EKS pod
kubectl exec -n er at-ai-editor-recommender-deployment-<pod-id> `
  --context eks-dev-real -- `
  cat /var/run/secrets/eks.amazonaws.com/serviceaccount/token `
  | Out-File -FilePath "$env:TEMP\irsa_token.txt" -Encoding ascii -NoNewline

# Assume Bedrock role
$env:AWS_ROLE_ARN = "arn:aws:iam::<ACCOUNT_ID>:role/acs-gtsai-dev-eks-bedrock-clusterrole"
$env:AWS_WEB_IDENTITY_TOKEN_FILE = "$env:TEMP\irsa_token.txt"

# Remove any SSO credentials that would take priority
Remove-Item Env:\AWS_ACCESS_KEY_ID, Env:\AWS_SECRET_ACCESS_KEY, Env:\AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
```

---

## Test Data

**Manuscript MS-999** — *"Deep learning approaches for early detection of immunotherapy resistance"*  
Authors: John Smith, Jane Doe, Robert Chen

| Editor | COI? | Reason |
|--------|------|--------|
| Dr. Emily Jones | ⚠ Flagged | Co-authored with John Smith (Nature Medicine 2023) |
| Dr. Kevin Lee | ✅ Approved | No overlap |
| Dr. Maria Smith | ✅ Approved | No overlap |

---

## Swagger Test Calls

**`POST /run-workflow`** on port 8000 — runs the full A2A + COI + HITL flow:
```json
{"manuscript_number": "MS-999", "auto_approve": true}
```

**A2A JSON-RPC `message/send`** on port 8000 — native SDK protocol (editor history):
```json
{
  "jsonrpc": "2.0",
  "id": "test-001",
  "method": "message/send",
  "params": {
    "message": {
      "role": "user",
      "parts": [{"kind": "text", "text": "Get editor history for: Dr. Emily Jones"}],
      "messageId": "msg-test-001"
    }
  }
}
```

**`POST /tasks/send`** on port 8001 — legacy adapter (COI check):
```json
{
  "id": "coi-MS-999",
  "message": {
    "role": "user",
    "parts": [{"text": "Check conflicts of interest.\nManuscript authors: [\"John Smith\", \"Jane Doe\", \"Robert Chen\"]\nCandidate editors: [\"Dr. Emily Jones\", \"Dr. Kevin Lee\", \"Dr. Maria Smith\"]"}]
  }
}
```

---

## Deploy to EKS Dev

```bash
# Apply shared IRSA service account (once)
kubectl apply -f k8s/dev/er-bedrock-sa.yaml --context eks-dev-real -n er

# Deploy both services
kubectl apply -f k8s/dev/langgraph-service/ --context eks-dev-real -n er
kubectl apply -f k8s/dev/strands-coi-service/ --context eks-dev-real -n er

# Verify
kubectl get pods -n er --context eks-dev-real
```

In-cluster DNS:
- LangGraph → `http://langgraph-svc.er.svc.cluster.local:8000`
- Strands COI → `http://strands-coi-svc.er.svc.cluster.local:8001`

---

## Repo Structure

```
├── fake_data.py                    # Test data (MS-999, 3 editors)
├── start.ps1                       # One-click launcher (PowerShell)
├── streamlit_app.py                # Streamlit HITL UI
├── pytest.ini                      # Test config (asyncio_mode=auto)
├── pyproject.toml                  # Project metadata & dependencies
│
├── langgraph_service/              # Orchestrator agent — :8000
│   ├── callback_server.py          # Entry point — assembles Starlette app
│   ├── agent_card.py               # A2A Agent Card (assign_editor, editor_history)
│   ├── a2a_handler.py              # A2A executor + SDK wiring + legacy adapter
│   ├── routes.py                   # REST endpoints (health, editors, COI, finalize)
│   ├── editor_utils.py             # Pure helpers (name parsing, reasoning, scoring)
│   ├── scoring.py                  # 5-dimension composite scoring + HITL thresholds
│   ├── Dockerfile
│   └── requirements.txt
│
├── strands_service/                # COI specialist agent — :8001
│   ├── server.py                   # Entry point — assembles Starlette app
│   ├── agent_card.py               # A2A Agent Card (check_conflicts)
│   ├── a2a_handler.py              # A2A executor + SDK wiring + legacy adapter
│   ├── coi_agent.py                # Strands agent with history tool (Bedrock/mock)
│   ├── Dockerfile
│   └── requirements.txt
│
├── tests/                          # 145 unit tests (pytest + httpx ASGI)
│   ├── test_callback_server.py     # LangGraph routes, A2A, agent card, compat (41)
│   ├── test_coi_agent.py           # COI agent, Strands agent card, health (22)
│   ├── test_scoring.py             # All scoring dimensions + HITL decisions (38)
│   ├── test_fake_data.py           # Data integrity checks (17)
│   └── test_streamlit_app.py       # UI helper functions (13)
│
├── k8s/dev/
│   ├── er-bedrock-sa.yaml          # IRSA ServiceAccount
│   ├── langgraph-service/          # Deployment + Service
│   └── strands-coi-service/        # Deployment + Service
│
└── .github/workflows/
    ├── docker-langgraph.yaml       # Builds on langgraph_service/** changes
    └── docker-strands.yaml         # Builds on strands_service/** changes
```
