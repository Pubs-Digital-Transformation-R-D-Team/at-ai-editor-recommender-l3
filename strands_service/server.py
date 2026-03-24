"""
Strands COI Service — A2A Server (port 8001)
─────────────────────────────────────────────
Uses the official **google/a2a-python SDK** for all A2A protocol handling.

Exposes (all managed by the SDK):
  GET  /.well-known/agent.json  →  Strands Agent Card
  POST /                        →  JSON-RPC 2.0 `message/send`
  POST /tasks/send              →  Legacy adapter (translates to SDK)
  GET  /health                  →  K8s health check

When LangGraph sends a `message/send` to this agent:
  1. The Strands COI Agent receives the message
  2. Agent internally calls get_editor_history tool for each editor
  3. get_editor_history makes A2A callback to LangGraph port 8000
  4. Agent reasons over history, identifies conflicts
  5. Returns {approved: [...], flagged: [...]} JSON
"""

import asyncio
import json
import logging
import os
import sys

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.agent_execution import AgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.events.event_queue import EventQueue
from a2a.server.agent_execution.context import RequestContext
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
    Artifact,
    Message,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

# Allow importing from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from strands_service.coi_agent import run_coi_check  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[Strands:8001]  %(message)s",
)
logger = logging.getLogger(__name__)


# ─── Agent Card (A2A SDK typed model) ───────────────────────────────────────

AGENT_CARD = AgentCard(
    name="COI Checker (Strands)",
    description=(
        "Checks conflict of interest between manuscript authors and candidate "
        "editors.  Fetches editor publication history from the Editor "
        "Recommender service and identifies co-authorship/collaboration "
        "conflicts."
    ),
    url="http://localhost:8001",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        AgentSkill(
            id="check_conflicts",
            name="Check Conflicts of Interest",
            description=(
                "Given manuscript authors and a list of candidate editors, "
                "returns approved editors and flagged editors with reasons."
            ),
            tags=["coi", "conflict-of-interest", "editors"],
        ),
    ],
)


# ─── Agent Executor (runs the real Strands agent logic) ─────────────────────

class StrandsCOIExecutor(AgentExecutor):
    """Wraps the Strands COI agent as an A2A SDK AgentExecutor."""

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Extract user message text from the A2A request
        user_msg = ""
        message = context.message
        if message and message.parts:
            for part in message.parts:
                if hasattr(part, "root") and hasattr(part.root, "text"):
                    user_msg += part.root.text
                elif hasattr(part, "text"):
                    user_msg += part.text

        task_id = context.task_id or "unknown"
        context_id = context.context_id or ""
        logger.info("Received COI task (id=%s): %s", task_id, user_msg[:120])

        # Emit "working" status update
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=task_id,
                contextId=context_id,
                final=False,
                status=TaskStatus(state=TaskState.working),
            )
        )

        # Run the synchronous Strands agent in a thread pool
        loop = asyncio.get_event_loop()
        result_text = await loop.run_in_executor(None, run_coi_check, user_msg)

        # Clean up / parse the output
        try:
            clean = result_text.strip()
            if clean.startswith("```"):
                clean = clean.split("```")[1]
                if clean.startswith("json"):
                    clean = clean[4:]
            parsed = json.loads(clean.strip())
            output = json.dumps(parsed, indent=2)
            logger.info(
                "COI complete — approved: %s | flagged: %s",
                [e if isinstance(e, str) else e.get("editor")
                 for e in parsed.get("approved", [])],
                [e if isinstance(e, str) else e.get("editor")
                 for e in parsed.get("flagged", [])],
            )
        except (json.JSONDecodeError, IndexError):
            logger.warning("COI result not clean JSON, returning raw")
            output = result_text

        # Enqueue the completed Task (SDK handles JSON-RPC response)
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(state=TaskState.completed),
                artifacts=[
                    Artifact(
                        artifactId=f"artifact-{task_id}",
                        parts=[Part(root=TextPart(text=output))],
                    ),
                ],
            )
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        logger.info("Task cancelled")
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=context.task_id or "unknown",
                contextId=context.context_id or "",
                final=True,
                status=TaskStatus(state=TaskState.canceled),
            )
        )


# ─── Build the A2A SDK application ──────────────────────────────────────────

executor = StrandsCOIExecutor()
task_store = InMemoryTaskStore()
request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
)
a2a_app = A2AStarletteApplication(
    agent_card=AGENT_CARD,
    http_handler=request_handler,
)

# The inner Starlette app that the SDK manages
_a2a_inner = a2a_app.build()


# ─── Legacy /tasks/send adapter ─────────────────────────────────────────────
# The LangGraph callback_server still calls POST /tasks/send with our old
# custom schema.  This adapter translates it to the SDK's JSON-RPC format
# and translates the response back.

async def legacy_tasks_send(request: Request):
    """Adapter: old POST /tasks/send → A2A SDK JSON-RPC message/send."""
    body = await request.json()
    task_id = body.get("id", "task-001")
    message_text = body["message"]["parts"][0]["text"]

    # Build the JSON-RPC request the SDK expects
    jsonrpc_body = {
        "jsonrpc": "2.0",
        "id": task_id,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": message_text}],
                "messageId": f"msg-{task_id}",
            },
        },
    }

    # Call the SDK app internally via ASGI transport
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_a2a_inner),
        base_url="http://localhost",
    ) as client:
        resp = await client.post("/", json=jsonrpc_body)
        rpc_result = resp.json()

    # Translate JSON-RPC result → legacy format
    result = rpc_result.get("result", {})
    artifacts = result.get("artifacts", [])
    if artifacts:
        parts = artifacts[0].get("parts", [])
        artifact_text = parts[0].get("text", "") if parts else ""
    else:
        artifact_text = json.dumps(result)

    return JSONResponse({
        "id": task_id,
        "status": {"state": result.get("status", {}).get("state", "completed")},
        "artifacts": [{"parts": [{"text": artifact_text}]}],
    })


# ─── Extra routes (health, legacy adapter) ──────────────────────────────────

async def health(request: Request):
    return JSONResponse({"status": "ok", "service": "strands-coi-checker"})


# Compose the full Starlette app
app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/tasks/send", legacy_tasks_send, methods=["POST"]),
    ],
)

# Mount the A2A SDK — serves /.well-known/agent.json + POST / (JSON-RPC)
app.mount("/", _a2a_inner)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Strands COI A2A server (SDK) on port 8001")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
