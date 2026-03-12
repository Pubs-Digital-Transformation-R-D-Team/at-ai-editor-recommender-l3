"""
Strands COI Service — A2A Server (port 8001)
─────────────────────────────────────────────
Exposes:
  GET  /.well-known/agent.json  →  Strands Agent Card (A2A discovery)
  POST /tasks/send              →  Runs COI check via Strands Agent

When LangGraph sends a task here:
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

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

# Allow importing from parent poc/ directory
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from strands_service.coi_agent import run_coi_check  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="[Strands:8001]  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Strands COI Checker",
    description=(
        "## Strands COI Agent — A2A Server\n\n"
        "This service is the **Strands COI agent** in a bidirectional A2A architecture:\n\n"
        "```\n"
        "  LangGraph (8000) ──── A2A task ────► Strands COI (8001)\n"
        "       ▲                                     │\n"
        "       └──────── A2A callback (history) ─────┘\n"
        "```\n\n"
        "### What this agent does\n"
        "1. Receives a COI check request from LangGraph\n"
        "2. For each candidate editor, calls `GET editor history` via A2A to LangGraph:8000\n"
        "3. Checks for co-authorship / collaboration conflicts\n"
        "4. Returns `{approved: [...], flagged: [...]}` JSON\n\n"
        "### Endpoints\n"
        "| Endpoint | Purpose |\n"
        "|----------|---------|\n"
        "| `GET /.well-known/agent.json` | A2A Agent Card discovery |\n"
        "| `POST /tasks/send` | Run COI check (full A2A flow) |\n"
        "| `GET /health` | Health check |\n"
    ),
    version="1.0.0",
)

# ─── A2A data models ────────────────────────────────────────────────────────

class Part(BaseModel):
    text: str = Field(
        ...,
        examples=[(
            "Check conflicts of interest.\n"
            "Manuscript authors: [\"John Smith\", \"Jane Doe\"]\n"
            "Candidate editors: [\"Dr. Emily Jones\", \"Dr. Kevin Lee\", \"Dr. Maria Smith\"]"
        )],
    )


class Message(BaseModel):
    role: str = Field(default="user", examples=["user"])
    parts: list[Part]


class TaskRequest(BaseModel):
    id: str = Field(default="task-001", examples=["coi-MS-999"])
    message: Message

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "summary": "COI check request (from LangGraph)",
                    "value": {
                        "id": "coi-MS-999",
                        "message": {
                            "role": "user",
                            "parts": [
                                {
                                    "text": (
                                        "Check conflicts of interest.\n"
                                        'Manuscript authors: ["John Smith", "Jane Doe", "Robert Chen"]\n'
                                        'Candidate editors: ["Dr. Emily Jones", "Dr. Kevin Lee", "Dr. Maria Smith"]\n'
                                        "For each editor, fetch their publication history and identify any co-authorship."
                                    )
                                }
                            ],
                        },
                    },
                }
            ]
        }
    }


class TaskStatus(BaseModel):
    state: str = "completed"


class ArtifactPart(BaseModel):
    text: str


class Artifact(BaseModel):
    parts: list[ArtifactPart]


class TaskResponse(BaseModel):
    id: str
    status: TaskStatus
    artifacts: list[Artifact]


# ─── Agent Card ─────────────────────────────────────────────────────────────

AGENT_CARD = {
    "name": "COI Checker (Strands)",
    "description": (
        "Checks conflict of interest between manuscript authors and candidate editors. "
        "Fetches editor publication history from the Editor Recommender service and "
        "identifies co-authorship or collaboration conflicts."
    ),
    "url": "http://localhost:8001",
    "version": "1.0.0",
    "skills": [
        {
            "id": "check_conflicts",
            "name": "Check Conflicts of Interest",
            "description": (
                "Given manuscript authors and a list of candidate editors, "
                "returns approved editors and flagged editors with reasons."
            ),
        }
    ],
}


@app.get("/.well-known/agent.json")
async def agent_card():
    logger.info("Agent Card requested")
    return AGENT_CARD


# ─── Task handler ────────────────────────────────────────────────────────────

@app.post(
    "/tasks/send",
    response_model=TaskResponse,
    summary="Run COI check (full Strands A2A flow)",
    description=(
        "Runs the full COI check pipeline via the Strands agent:\n\n"
        "1. Parses manuscript authors and candidate editors from the message text\n"
        "2. For **each** candidate editor, makes an A2A callback to LangGraph port 8000 "
        "to fetch that editor's publication history\n"
        "3. Checks for co-authorship or recent collaboration conflicts\n"
        "4. Returns a JSON artifact: `{\\\"approved\\\": [...], \\\"flagged\\\": [...]}`\n\n"
        "**Message format expected in `parts[0].text`:**\n"
        "```\n"
        "Manuscript authors: [\"Author A\", \"Author B\"]\n"
        "Candidate editors: [\"Dr. X\", \"Dr. Y\", \"Dr. Z\"]\n"
        "```\n\n"
        "> ⚡ Requires LangGraph service running on port 8000 to serve editor history callbacks.\n\n"
        "> 🤖 Set `MOCK_COI=true` to bypass Bedrock and use rule-based conflict detection."
    ),
    tags=["A2A Task"],
)
async def handle_task(request: TaskRequest):
    message_text = request.message.parts[0].text
    logger.info("Received COI task (id=%s): %s", request.id, message_text[:120])

    # Run the Strands agent in a thread pool (it's synchronous internally)
    loop = asyncio.get_event_loop()
    result_text = await loop.run_in_executor(None, run_coi_check, message_text)

    # Try to parse and re-serialize cleanly
    try:
        # Strip markdown fences if model added them
        clean = result_text.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        parsed = json.loads(clean.strip())
        output = json.dumps(parsed, indent=2)
        logger.info(
            "COI task complete — approved: %s | flagged: %s",
            [e if isinstance(e, str) else e.get("editor") for e in parsed.get("approved", [])],
            [e if isinstance(e, str) else e.get("editor") for e in parsed.get("flagged", [])],
        )
    except (json.JSONDecodeError, IndexError):
        logger.warning("COI result was not clean JSON, returning raw")
        output = result_text

    return TaskResponse(
        id=request.id,
        status=TaskStatus(state="completed"),
        artifacts=[Artifact(parts=[ArtifactPart(text=output)])],
    )


# ─── Health check ────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "strands-coi-checker"}


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting Strands COI A2A server on port 8001")
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
