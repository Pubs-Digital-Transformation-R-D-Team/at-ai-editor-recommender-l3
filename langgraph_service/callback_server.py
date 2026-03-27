"""
LangGraph A2A Callback Server (port 8000)
─────────────────────────────────────────
Entry point that wires together the separate modules:

* ``agent_card.py``   — A2A Agent Card definition
* ``a2a_handler.py``  — A2A executor + legacy adapter
* ``editor_utils.py`` — Editor reasoning & score enrichment helpers
* ``routes.py``       — REST endpoint handlers (workflow, COI, browse data)
* ``scoring.py``      — Composite scoring & HITL decision logic

Exposes (A2A via SDK):
  GET  /.well-known/agent.json  →  LangGraph Agent Card
  POST /                        →  JSON-RPC 2.0 ``message/send`` (editor history)
  POST /tasks/send              →  Legacy adapter (translates to SDK)

Exposes (non-A2A, regular REST):
  POST /run-workflow            →  Full editor assignment demo (A2A + COI)
  POST /check-coi               →  Phase 1 for Streamlit UI
  POST /finalize                →  Phase 2 for Streamlit UI
  GET  /editors                 →  Browse editor data
  GET  /manuscript/{number}     →  Browse manuscript data
  GET  /health                  →  K8s health check
"""

import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route

from langgraph_service.a2a_handler import a2a_inner_app, legacy_tasks_send
from langgraph_service.routes import (
    check_coi_only,
    finalize_assignment,
    get_editor_history,
    get_manuscript,
    health,
    list_editors,
    resilience_dlq,
    resilience_dlq_clear,
    resilience_reset,
    resilience_status,
    run_workflow,
)

# ── Re-export helpers so existing imports (tests, etc.) keep working ─────────
from langgraph_service.editor_utils import (  # noqa: F401
    build_reasoning as _build_reasoning,
    build_reasoning_points as _build_reasoning_points,
    editor_details as _editor_details,
    extract_editor_name as _extract_editor_name,
)

logging.basicConfig(
    level=logging.INFO,
    format="[LangGraph:8000] %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Compose the full Starlette app ─────────────────────────────────────────

app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/tasks/send", legacy_tasks_send, methods=["POST"]),
        Route("/editors", list_editors, methods=["GET"]),
        Route("/manuscript/{manuscript_number}", get_manuscript, methods=["GET"]),
        Route("/editor-history/{editor_name:path}", get_editor_history, methods=["GET"]),
        Route("/run-workflow", run_workflow, methods=["POST"]),
        Route("/check-coi", check_coi_only, methods=["POST"]),
        Route("/finalize", finalize_assignment, methods=["POST"]),
        Route("/resilience/status", resilience_status, methods=["GET"]),
        Route("/resilience/dlq", resilience_dlq, methods=["GET"]),
        Route("/resilience/dlq/clear", resilience_dlq_clear, methods=["POST"]),
        Route("/resilience/reset", resilience_reset, methods=["POST"]),
    ],
)

# Mount the A2A SDK — serves /.well-known/agent.json + POST / (JSON-RPC)
app.mount("/", a2a_inner_app)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    logger.info("Starting LangGraph A2A callback server (SDK) on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
