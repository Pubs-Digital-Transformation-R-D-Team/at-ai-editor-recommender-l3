"""
Strands COI Service — A2A Server (port 8001)
─────────────────────────────────────────────
Entry point that wires together the separate modules:

* ``agent_card.py``   — A2A Agent Card definition
* ``a2a_handler.py``  — A2A executor + legacy adapter
* ``coi_agent.py``    — Strands COI agent logic (Bedrock / mock)

Exposes (all managed by the SDK):
  GET  /.well-known/agent.json  →  Strands Agent Card
  POST /                        →  JSON-RPC 2.0 ``message/send``
  POST /tasks/send              →  Legacy adapter (translates to SDK)
  GET  /health                  →  K8s health check

When LangGraph sends a ``message/send`` to this agent:
  1. The Strands COI Agent receives the message
  2. Agent internally calls ``get_editor_history`` tool for each editor
  3. ``get_editor_history`` makes A2A callback to LangGraph port 8000
  4. Agent reasons over history, identifies conflicts
  5. Returns ``{approved: [...], flagged: [...]}`` JSON
"""

import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from strands_service.a2a_handler import a2a_inner_app, legacy_tasks_send

logging.basicConfig(
    level=logging.INFO,
    format="[Strands:8001]  %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Health check ────────────────────────────────────────────────────────────

async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "strands-coi-checker"})


# ─── Compose the full Starlette app ─────────────────────────────────────────

app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/tasks/send", legacy_tasks_send, methods=["POST"]),
    ],
)

# Mount the A2A SDK — serves /.well-known/agent.json + POST / (JSON-RPC)
app.mount("/", a2a_inner_app)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8001"))
    logger.info("Starting Strands COI A2A server (SDK) on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
