"""
LangGraph A2A Callback Server (port 8000)
─────────────────────────────────────────
Uses the official **google/a2a-python SDK** for all A2A protocol handling.

Exposes (A2A via SDK):
  GET  /.well-known/agent.json  →  LangGraph Agent Card
  POST /                        →  JSON-RPC 2.0 `message/send` (editor history)
  POST /tasks/send              →  Legacy adapter (translates to SDK)

Exposes (non-A2A, regular REST):
  POST /run-workflow            →  Full editor assignment demo (A2A + COI)
  POST /check-coi               →  Phase 1 for Streamlit UI
  POST /finalize                →  Phase 2 for Streamlit UI
  GET  /editors                 →  Browse editor data
  GET  /manuscript/{number}     →  Browse manuscript data
  GET  /health                  →  K8s health check
"""

import asyncio
import json
import logging
import os
import re
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

logging.basicConfig(
    level=logging.INFO,
    format="[LangGraph:8000] %(message)s",
)
logger = logging.getLogger(__name__)

STRANDS_URL = os.getenv("STRANDS_COI_URL", "http://localhost:8001")


# ─── A2A Agent Card (SDK typed model) ────────────────────────────────────────

AGENT_CARD = AgentCard(
    name="Editor Recommender (LangGraph)",
    description=(
        "Assigns peer-review editors to manuscripts. "
        "Also provides editor publication history for COI checks."
    ),
    url="http://localhost:8000",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=False),
    default_input_modes=["text"],
    default_output_modes=["text"],
    skills=[
        AgentSkill(
            id="assign_editor",
            name="Assign Editor",
            description="Full editor assignment workflow for a manuscript",
            tags=["editor", "assignment", "workflow"],
        ),
        AgentSkill(
            id="editor_history",
            name="Editor Publication History",
            description=(
                "Returns publications and co-authors for a given editor. "
                "Used by COI checker to detect conflicts."
            ),
            tags=["editor", "history", "publications"],
        ),
    ],
)


# ─── Agent Executor (handles A2A tasks from Strands) ────────────────────────

class EditorHistoryExecutor(AgentExecutor):
    """Handles `message/send` from the Strands COI agent.

    When Strands says "Get editor history for: Dr. X", this executor
    returns that editor's publication history from fake_data.
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
            editor_name = _extract_editor_name(user_msg)
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
_a2a_inner = a2a_app.build()


# ─── Legacy /tasks/send adapter ─────────────────────────────────────────────

async def legacy_tasks_send(request: Request):
    """Adapter: old POST /tasks/send → A2A SDK JSON-RPC message/send."""
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
        transport=httpx.ASGITransport(app=_a2a_inner),
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


def _extract_editor_name(text: str) -> str:
    """Parse 'Get editor history for: Dr. Emily Jones' → 'Dr. Emily Jones'"""
    for separator in ["for:", "for "]:
        if separator in text.lower():
            idx = text.lower().index(separator) + len(separator)
            return text[idx:].strip().strip('"').strip("'")
    return text.strip()


# ─── Editor detail / reasoning helpers ───────────────────────────────────────

def _build_reasoning_points(editor_name: str, editor: dict, matched: set, flagged_names: set) -> list[str]:
    """Return a list of concise bullet-point reasons for/against this editor."""
    points = []
    load = editor.get("current_load", 0)
    max_load = editor.get("max_load", 5)
    capacity = max_load - load
    expertise = editor.get("expertise", [])

    # Topic match
    if matched:
        points.append(f"✅ Expertise directly matches manuscript topics: {', '.join(sorted(matched))}")
    else:
        other = [e for e in expertise if e not in matched]
        points.append(
            f"⚠️ No direct topic overlap (expertise: {', '.join(other[:3]) or 'general'})"
        )

    # Workload / capacity
    if capacity >= 3:
        points.append(f"✅ Good capacity — {load}/{max_load} manuscripts assigned, {capacity} slots free")
    elif capacity == 2:
        points.append(f"✅ Available — {load}/{max_load} manuscripts assigned, {capacity} slots free")
    elif capacity == 1:
        points.append(f"⚠️ Nearly full — only 1 slot remaining ({load}/{max_load} manuscripts)")
    else:
        points.append(f"❌ At capacity — {load}/{max_load} manuscripts (no slots free)")

    # COI status
    if editor_name not in flagged_names:
        points.append("✅ No conflict of interest detected with manuscript authors")
    else:
        points.append("❌ Conflict of interest — co-authorship or relationship with an author detected")

    return points


def _build_reasoning(editor_name: str, editor: dict, matched: set, flagged_names: set) -> str:
    """Return a single-sentence summary suitable for the editor card."""
    load = editor.get("current_load", 0)
    max_load = editor.get("max_load", 5)
    capacity = max_load - load
    topic_str = ", ".join(sorted(matched)) if matched else "general relevance"
    coi_str = "No COI detected" if editor_name not in flagged_names else "COI flagged"
    cap_str = f"{capacity} slot{'s' if capacity != 1 else ''} free"
    return f"Topic match: {topic_str}. Capacity: {load}/{max_load} ({cap_str}). {coi_str}."


def _editor_details(editor_name: str, coi_result: dict) -> dict:
    """Enrich an editor record with COI status and topic-match reasoning."""
    editor = next(
        (e for e in fake_data.EDITORS.values() if e["name"] == editor_name),
        {"name": editor_name, "expertise": [], "current_load": 0, "max_load": 5},
    )
    ms = fake_data.MANUSCRIPTS.get("MS-999", {})
    ms_topics = set(ms.get("topics", []))
    expertise_set = set(editor.get("expertise", []))
    matched = ms_topics & expertise_set

    flagged_names = {
        (f["editor"] if isinstance(f, dict) else f)
        for f in coi_result.get("flagged", [])
    }
    flag_entry = next(
        (f for f in coi_result.get("flagged", [])
         if (f if isinstance(f, str) else f.get("editor")) == editor_name),
        None,
    )

    return {
        "name": editor_name,
        "orcid": editor.get("id", "N/A"),
        "person_id": editor.get("person_id", "N/A"),
        "expertise": editor.get("expertise", []),
        "current_load": editor.get("current_load", 0),
        "max_load": editor.get("max_load", 5),
        "topic_match": sorted(matched),
        "topic_match_score": len(matched),
        "coi_status": "flagged" if editor_name in flagged_names else "approved",
        "coi_reason": (
            flag_entry.get("reason", "Conflict detected")
            if isinstance(flag_entry, dict)
            else str(flag_entry) if flag_entry else None
        ),
        "reasoning": _build_reasoning(editor_name, editor, matched, flagged_names),
        "reasoning_points": _build_reasoning_points(editor_name, editor, matched, flagged_names),
    }


# ─── Browse data endpoints (plain Starlette) ─────────────────────────────────

async def list_editors(request: Request):
    return JSONResponse({"editors": list(fake_data.EDITORS.values())})


async def get_manuscript(request: Request):
    ms_num = request.path_params.get("manuscript_number", "MS-999")
    try:
        return JSONResponse(fake_data.get_manuscript(ms_num))
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


async def get_editor_history(request: Request):
    name = request.path_params.get("editor_name", "Dr. Emily Jones")
    return JSONResponse(fake_data.get_editor_history(name))


# ─── Full workflow endpoint ───────────────────────────────────────────────────

async def run_workflow(request: Request):
    body = await request.json()
    ms_number = body.get("manuscript_number", "MS-999")
    auto_approve = body.get("auto_approve", True)

    try:
        ms = fake_data.get_manuscript(ms_number)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    authors = ms["authors"]
    editors = [e["name"] for e in fake_data.EDITORS.values()]
    logger.info("[Workflow] Loaded manuscript %s — authors: %s", ms_number, authors)

    # A2A call to Strands COI service
    coi_message = (
        f"Check conflicts of interest.\n"
        f"Manuscript authors: {json.dumps(authors)}\n"
        f"Candidate editors: {json.dumps(editors)}\n"
        f"For each editor, fetch their publication history and identify any co-authorship "
        f"or recent collaboration with the manuscript authors."
    )
    coi_payload = {
        "id": f"coi-{ms_number}",
        "message": {"role": "user", "parts": [{"text": coi_message}]},
    }

    logger.info("[Workflow] → A2A POST to Strands COI service")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            coi_resp = await client.post(f"{STRANDS_URL}/tasks/send", json=coi_payload)
            coi_resp.raise_for_status()
    except httpx.ConnectError:
        return JSONResponse(
            {"error": f"Strands COI service not running at {STRANDS_URL}"},
            status_code=503,
        )

    coi_text = coi_resp.json()["artifacts"][0]["parts"][0]["text"]
    try:
        clean = re.sub(r'<thinking>.*?</thinking>', '', coi_text, flags=re.DOTALL)
        match = re.search(r'(\{.*\})', clean, re.DOTALL)
        coi_result = json.loads(match.group(1)) if match else json.loads(coi_text)
    except (json.JSONDecodeError, AttributeError):
        coi_result = {"raw": coi_text, "approved": [], "flagged": []}

    logger.info("[Workflow] ← COI result: %s", coi_result)

    approved = coi_result.get("approved", [])
    flagged = coi_result.get("flagged", [])
    hitl_triggered = len(flagged) > 0

    if hitl_triggered and auto_approve and approved:
        selected_editor_name = approved[0]
        hitl_decision = "option_1_auto_approved"
    elif hitl_triggered and not auto_approve:
        fe = flagged[0]
        selected_editor_name = fe if isinstance(fe, str) else fe.get("editor")
        hitl_decision = "option_2_override"
    elif approved:
        selected_editor_name = approved[0]
        hitl_decision = "no_conflict_auto"
    else:
        selected_editor_name = "ESCALATED"
        hitl_decision = "option_3_escalate"

    selected_editor = next(
        (e for e in fake_data.EDITORS.values() if e["name"] == selected_editor_name),
        {"name": selected_editor_name, "id": "N/A", "person_id": "N/A"},
    )
    runner_up = approved[1] if len(approved) > 1 else (approved[0] if approved and approved[0] != selected_editor_name else "N/A")

    return JSONResponse({
        "manuscript": {"number": ms_number, "title": ms["title"], "authors": authors},
        "coi_check": {
            "a2a_call": f"POST {STRANDS_URL}/tasks/send",
            "strands_callback": "POST http://localhost:8000/tasks/send (called by Strands for each editor)",
            "approved": approved, "flagged": flagged,
        },
        "hitl": {"triggered": hitl_triggered, "decision": hitl_decision},
        "final_assignment": {
            "editor_name": selected_editor["name"],
            "orcid": selected_editor.get("id", "N/A"),
            "person_id": selected_editor.get("person_id", "N/A"),
            "runner_up": runner_up,
        },
    })


# ─── Streamlit UI endpoints ──────────────────────────────────────────────────

async def check_coi_only(request: Request):
    """Phase 1 — Load manuscript and run COI check via A2A."""
    body = await request.json()
    ms_number = body.get("manuscript_number", "MS-999")

    try:
        ms = fake_data.get_manuscript(ms_number)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)

    authors = ms["authors"]
    editors = [e["name"] for e in fake_data.EDITORS.values()]

    coi_message = (
        f"Check conflicts of interest.\n"
        f"Manuscript authors: {json.dumps(authors)}\n"
        f"Candidate editors: {json.dumps(editors)}\n"
        f"For each editor, fetch their publication history and identify any co-authorship "
        f"or recent collaboration with the manuscript authors."
    )
    coi_payload = {
        "id": f"coi-{ms_number}",
        "message": {"role": "user", "parts": [{"text": coi_message}]},
    }

    logger.info("[check-coi] → A2A POST to Strands COI")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            coi_resp = await client.post(f"{STRANDS_URL}/tasks/send", json=coi_payload)
            coi_resp.raise_for_status()
    except httpx.ConnectError:
        return JSONResponse(
            {"error": f"Strands COI service not reachable at {STRANDS_URL}"},
            status_code=503,
        )

    coi_text = coi_resp.json()["artifacts"][0]["parts"][0]["text"]
    try:
        clean = re.sub(r"<thinking>.*?</thinking>", "", coi_text, flags=re.DOTALL)
        match = re.search(r"(\{.*\})", clean, re.DOTALL)
        coi_result = json.loads(match.group(1)) if match else json.loads(coi_text)
    except (json.JSONDecodeError, AttributeError):
        coi_result = {"approved": [], "flagged": []}

    logger.info("[check-coi] ← COI result: %s", coi_result)

    all_editor_names = (
        [a if isinstance(a, str) else a.get("editor") for a in coi_result.get("approved", [])]
        + [f if isinstance(f, str) else f.get("editor") for f in coi_result.get("flagged", [])]
    )
    editor_profiles = {name: _editor_details(name, coi_result) for name in all_editor_names}

    logger.info(
        "[check-coi] Complete — approved: %s | flagged: %s | waiting for human decision…",
        [a if isinstance(a, str) else a.get("editor") for a in coi_result.get("approved", [])],
        [f if isinstance(f, str) else f.get("editor") for f in coi_result.get("flagged", [])],
    )

    return JSONResponse({
        "manuscript": {
            "number": ms_number, "title": ms["title"], "authors": authors,
            "abstract": ms.get("abstract", ""), "topics": ms.get("topics", []),
            "journal": ms.get("journal", ""),
        },
        "coi_result": coi_result,
        "editor_profiles": editor_profiles,
        "a2a_trace": [
            f"LangGraph → Strands COI:  POST {STRANDS_URL}/tasks/send",
            *[f"  Strands → LangGraph:  POST :8000/tasks/send  [history for {name}]"
              for name in all_editor_names],
            "  Strands → LangGraph:  COI result returned",
        ],
    })


async def finalize_assignment(request: Request):
    """Phase 2 — Apply human HITL decision and return final assignment."""
    body = await request.json()
    coi_result = body.get("coi_result", {})
    decision = body.get("human_decision", "1")

    logger.info("[finalize] Human decision received: option %s", decision)

    approved = [a if isinstance(a, str) else a.get("editor") for a in coi_result.get("approved", [])]
    flagged_raw = coi_result.get("flagged", [])
    flagged = [f if isinstance(f, str) else f.get("editor") for f in flagged_raw]

    if decision == "1":
        selected_name = approved[0] if approved else "N/A"
        decision_label = "Approved — AI recommendation accepted"
    elif decision == "2":
        selected_name = approved[1] if len(approved) > 1 else (approved[0] if approved else "N/A")
        decision_label = "Approved — runner-up selected"
    elif decision == "3":
        selected_name = flagged[0] if flagged else "N/A"
        decision_label = "Override — flagged editor assigned by human"
    else:
        selected_name = "ESCALATED"
        decision_label = "Escalated — referred to editor-in-chief"

    logger.info("[finalize] Decision: %s → selected editor: %s", decision_label, selected_name)

    selected = _editor_details(selected_name, coi_result) if selected_name != "ESCALATED" else {
        "name": "ESCALATED", "orcid": "N/A", "person_id": "N/A",
        "expertise": [], "reasoning": "Referred to editor-in-chief for manual assignment.",
    }
    runner_up_name = next((a for a in approved if a != selected_name), None)
    runner_up = _editor_details(runner_up_name, coi_result) if runner_up_name else None

    logger.info(
        "[finalize] Final assignment: %s (runner-up: %s) | approved: %d, flagged: %d",
        selected_name,
        runner_up_name or "none",
        len(approved),
        len(flagged),
    )

    return JSONResponse({
        "selected_editor": selected,
        "runner_up": runner_up,
        "decision_label": decision_label,
        "human_decision": decision,
        "coi_summary": {
            "approved_count": len(approved),
            "flagged_count": len(flagged),
            "flagged_editors": flagged_raw,
        },
    })


# ─── Health check ────────────────────────────────────────────────────────────

async def health(request: Request):
    return JSONResponse({"status": "ok"})


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
    ],
)

# Mount the A2A SDK — serves /.well-known/agent.json + POST / (JSON-RPC)
app.mount("/", _a2a_inner)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting LangGraph A2A callback server (SDK) on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
