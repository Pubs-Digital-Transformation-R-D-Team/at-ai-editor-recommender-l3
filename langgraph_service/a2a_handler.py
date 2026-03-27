"""
A2A Protocol Handler — EditorHistoryExecutor + Legacy Adapter
─────────────────────────────────────────────────────────────
Handles incoming A2A ``message/send`` requests from the Strands COI agent.

When Strands asks "Get editor history for: Dr. X", the executor looks up
that editor's publication history from ``fake_data`` and returns it as
an A2A artifact.

Also provides a **legacy adapter** at ``POST /tasks/send`` that translates
the old REST-style payload into a proper JSON-RPC ``message/send`` call
handled by the SDK.
"""

import json
import logging
import os
import sys

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

# Allow importing fake_data from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import fake_data  # noqa: E402

from langgraph_service.agent_card import AGENT_CARD
from langgraph_service.editor_utils import extract_editor_name

logger = logging.getLogger(__name__)


# ─── A2A Agent Executor ──────────────────────────────────────────────────────

class EditorHistoryExecutor(AgentExecutor):
    """Handles ``message/send`` from the Strands COI agent.

    When Strands says "Get editor history for: Dr. X", this executor
    returns that editor's publication history from ``fake_data``.
    """

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        # Extract the user message text
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
        logger.info("Received task: %s", user_msg[:120])

        # Route: editor history request
        if "editor history" in user_msg.lower() or "get history" in user_msg.lower():
            editor_name = extract_editor_name(user_msg)
            logger.info("Serving editor history for: %s", editor_name)
            history = fake_data.get_editor_history(editor_name)
            result_text = json.dumps(history, indent=2)
            logger.info(
                "Editor history returned — coauthors: %s",
                history.get("coauthors", []),
            )
        else:
            logger.warning("Unknown task type: %s", user_msg[:80])
            result_text = json.dumps({"error": "Unknown task type"})

        # Enqueue the completed Task
        await event_queue.enqueue_event(
            Task(
                id=task_id,
                contextId=context_id,
                status=TaskStatus(state=TaskState.completed),
                artifacts=[
                    Artifact(
                        artifactId=f"artifact-{task_id}",
                        parts=[Part(root=TextPart(text=result_text))],
                    ),
                ],
            )
        )

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                taskId=context.task_id or "unknown",
                contextId=context.context_id or "",
                final=True,
                status=TaskStatus(state=TaskState.canceled),
            )
        )


# ─── Build A2A SDK application ──────────────────────────────────────────────

executor = EditorHistoryExecutor()
task_store = InMemoryTaskStore()
request_handler = DefaultRequestHandler(
    agent_executor=executor,
    task_store=task_store,
)
a2a_app = A2AStarletteApplication(
    agent_card=AGENT_CARD,
    http_handler=request_handler,
)

#: The inner ASGI app that handles ``/.well-known/agent.json`` and ``POST /``
a2a_inner_app = a2a_app.build()


# ─── Legacy /tasks/send adapter ─────────────────────────────────────────────

async def legacy_tasks_send(request: Request):
    """Adapter: old ``POST /tasks/send`` → A2A SDK JSON-RPC ``message/send``.

    The Strands COI agent (and the old curl-based workflow) posts to this
    endpoint.  We translate it into the JSON-RPC envelope the SDK expects,
    forward it internally, and re-shape the response into the legacy format.
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
