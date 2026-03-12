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

# Terminal 3 — Run full workflow via CLI
PYTHONPATH=. MOCK_COI=true MOCK_REACT=true python run_poc.py
```

Swagger UIs:
- http://localhost:8000/docs — LangGraph (orchestrator + `/run-workflow`)
- http://localhost:8001/docs — Strands COI agent

---

## Mock vs Live Mode

| Env var | Effect |
|---------|--------|
| `MOCK_REACT=true` | LangGraph bypasses Bedrock, parses manifest directly |
| `MOCK_COI=true` | Strands bypasses Bedrock, uses rule-based conflict detection |
| *(unset)* | Both agents use Nova Premier via AWS Bedrock |

A2A calls between services are **always real HTTP** regardless of mock mode.

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
$env:AWS_ROLE_ARN = "arn:aws:iam::412381768680:role/acs-gtsai-dev-eks-bedrock-clusterrole"
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

**`POST /tasks/send`** on port 8000 — A2A callback (editor history lookup):
```json
{
  "id": "test-001",
  "message": {"role": "user", "parts": [{"text": "Get editor history for: Dr. Emily Jones"}]}
}
```

**`POST /tasks/send`** on port 8001 — COI check directly to Strands:
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
├── run_poc.py                      # CLI entry point with HITL prompt
├── langgraph_service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── callback_server.py          # FastAPI :8000 — A2A + /run-workflow
│   ├── graph.py                    # LangGraph state machine
│   └── react_agent.py              # Nova Premier ReAct loop
├── strands_service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── server.py                   # FastAPI :8001 — COI A2A endpoint
│   └── coi_agent.py                # Strands agent with history tool
├── k8s/dev/
│   ├── er-bedrock-sa.yaml          # IRSA ServiceAccount
│   ├── langgraph-service/          # Deployment + Service
│   └── strands-coi-service/        # Deployment + Service
└── .github/workflows/
    ├── docker-langgraph.yaml       # Builds on langgraph_service/** changes
    └── docker-strands.yaml         # Builds on strands_service/** changes
```
