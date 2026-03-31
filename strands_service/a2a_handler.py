"""
A2A Protocol Handler — Strands COI Executor + Legacy Adapter
────────────────────────────────────────────────────────────
Handles incoming A2A ``message/send`` requests from the LangGraph
orchestrator.

When LangGraph sends a COI check request:
  1. ``StrandsCOIExecutor`` receives the message via the SDK
  2. Delegates to ``run_coi_check()`` (from ``coi_agent.py``)
  3. Cleans the response JSON and returns it as an A2A artifact

Also provides a **legacy adapter** at ``POST /tasks/send`` that translates
the old REST-style payload into a proper JSON-RPC ``message/send`` call
handled by the SDK.
"""

import asyncio
import json
import logging
import os

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse

from a2a.server.agent_execution import AgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.events.event_queue import EventQueue
from a2a.server.agent_execution.context import RequestContext
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    Artifact,
    Part,
    Task,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)

from strands_service.agent_card import AGENT_CARD, SKILLS
from strands_service.coi_agent import MOCK_COI, build_coi_agent, run_coi_check

logger = logging.getLogger(__name__)


# ─── A2A Agent Executor ──────────────────────────────────────────────────────

class StrandsCOIExecutor(AgentExecutor):
    """Wraps the Strands COI agent as an A2A SDK ``AgentExecutor``.

    Receives a free-text message containing manuscript authors and
    candidate editors, runs the COI analysis (either via Bedrock or
    rule-based mock), and returns the ``{approved, flagged}`` JSON.
    """

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
        loop = asyncio.get_running_loop()
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
                [
                    e if isinstance(e, str) else e.get("editor")
                    for e in parsed.get("approved", [])
                ],
                [
                    e if isinstance(e, str) else e.get("editor")
                    for e in parsed.get("flagged", [])
                ],
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


# ─── Build A2A SDK application ──────────────────────────────────────────────

if MOCK_COI:
    # Mock mode: use manual executor (no Bedrock credentials needed)
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
    a2a_inner_app = a2a_app.build()
else:
    # Real mode: use Strands A2AServer (wraps the agent automatically)
    from strands.multiagent.a2a.server import A2AServer

    a2a_server = A2AServer(
        agent=build_coi_agent(),
        port=int(os.getenv("PORT", "8001")),
        skills=SKILLS,
    )
    a2a_inner_app = a2a_server.to_starlette_app()

#: The inner ASGI app that handles ``/.well-known/agent.json`` and ``POST /``


# ─── Legacy /tasks/send adapter ─────────────────────────────────────────────

async def legacy_tasks_send(request: Request):
    """Adapter: old ``POST /tasks/send`` → A2A SDK JSON-RPC ``message/send``.

    The LangGraph callback server posts to this endpoint using the old custom
    schema.  We translate into the JSON-RPC envelope the SDK expects, forward
    internally, and re-shape the response back into the legacy format.
    """
    body = await request.json()
    task_id = body.get("id", "task-001")
    message_text = body["message"]["parts"][0]["text"]

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

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=a2a_inner_app),
        base_url="http://localhost",
    ) as client:
        resp = await client.post("/", json=jsonrpc_body)
        rpc_result = resp.json()

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
