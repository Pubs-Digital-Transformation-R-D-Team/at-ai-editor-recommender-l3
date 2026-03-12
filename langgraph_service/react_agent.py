"""
ReAct Loop — editor_assignment node
────────────────────────────────────
Uses Bedrock Converse API with toolConfig (tool calling / function calling).

The LLM runs in a loop:
  1. Receives manuscript info + available editors
  2. Decides: "I should check conflicts" → calls check_conflicts tool
  3. check_conflicts → A2A POST to Strands COI service (port 8001)
  4. LLM receives COI result → makes final recommendation

The LLM decides WHEN to call the tool and whether to call it at all.
This is NOT hardcoded — genuine autonomous reasoning.
"""

import json
import logging
import os
import re

import aioboto3
import httpx

logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-premier-v1:0")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
STRANDS_URL = os.getenv("STRANDS_COI_URL", "http://localhost:8001")

# ── Mock mode: bypass Bedrock (useful when AWS credentials are unavailable) ──
# Set MOCK_REACT=true to enable. A2A call to Strands COI still runs in both modes.
MOCK_REACT = os.getenv("MOCK_REACT", "false").lower() in ("true", "1", "yes")

# ─── Tool definition sent to Bedrock ────────────────────────────────────────

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "check_conflicts",
                "description": (
                    "Check conflict of interest (COI) between manuscript authors and "
                    "candidate editors. Call this tool before making a final editor "
                    "recommendation to ensure there are no ethical conflicts. "
                    "Returns a JSON object with 'approved' (list of clean editors) and "
                    "'flagged' (list of editors with conflicts including reasons)."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "authors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Full names of the manuscript authors",
                            },
                            "candidate_editors": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Full names of candidate editors to check",
                            },
                        },
                        "required": ["authors", "candidate_editors"],
                    }
                },
            }
        }
    ]
}

SYSTEM_PROMPT = (
    "You are an expert scientific editor assignment system. "
    "Your job is to recommend the most suitable peer-review editor for a manuscript. "
    "IMPORTANT: Always use the check_conflicts tool before making your final recommendation "
    "to ensure there are no conflicts of interest. "
    "After receiving the COI check result, return your recommendation as a JSON object with keys: "
    "selectedEditorName, selectedEditorOrcId, selectedEditorPersonId, reasoning, runnerUp, "
    "filteredOutEditors. Return ONLY the JSON, no markdown, no extra text."
)


# ─── A2A call to Strands COI service ────────────────────────────────────────

async def _call_strands_coi(authors: list[str], candidate_editors: list[str]) -> dict:
    """
    Send a COI check task to the Strands service via A2A protocol.
    Strands will internally call back to LangGraph (/tasks/send) for editor history.
    """
    task_message = (
        f"Check conflicts of interest.\n"
        f"Manuscript authors: {json.dumps(authors)}\n"
        f"Candidate editors: {json.dumps(candidate_editors)}\n"
        f"For each editor, fetch their publication history and identify any co-authorship "
        f"or recent collaboration with the manuscript authors."
    )

    payload = {
        "id": "coi-task-001",
        "message": {
            "role": "user",
            "parts": [{"text": task_message}],
        },
    }

    logger.info("[LangGraph] → A2A POST %s/tasks/send", STRANDS_URL)
    logger.info("[LangGraph]   Checking COI for authors=%s editors=%s", authors, candidate_editors)

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{STRANDS_URL}/tasks/send", json=payload)
        response.raise_for_status()
        data = response.json()

    result_text = data["artifacts"][0]["parts"][0]["text"]
    logger.info("[LangGraph] ← A2A response from Strands received")

    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        logger.warning("[LangGraph] COI response was not JSON, wrapping raw text")
        return {"raw": result_text, "approved": [], "flagged": []}


# ─── ReAct loop ─────────────────────────────────────────────────────────────

async def run_react_editor_assignment(
    manuscript_info: str,
    available_editors: str,
) -> tuple[str, dict | None]:
    """
    Run the ReAct loop for editor assignment.

    Returns:
        (llm_final_text, coi_result)
        coi_result is None if the LLM never called check_conflicts.
    """
    if MOCK_REACT:
        return await _run_react_mock(manuscript_info, available_editors)

    session = aioboto3.Session()
    coi_result: dict | None = None

    prompt = (
        f"Please assign the most suitable editor for this manuscript.\n\n"
        f"## Manuscript Information\n{manuscript_info}\n\n"
        f"## Available Editors\n{available_editors}\n\n"
        f"Remember to check for conflicts of interest before making your recommendation."
    )

    messages = [{"role": "user", "content": [{"text": prompt}]}]

    logger.info("[LangGraph] Starting ReAct loop for editor assignment")

    async with session.client("bedrock-runtime", region_name=REGION) as bedrock:
        iteration = 0
        while True:
            iteration += 1
            logger.info("[LangGraph] ReAct iteration %d", iteration)

            response = await bedrock.converse(
                modelId=MODEL_ID,
                system=[{"text": SYSTEM_PROMPT}],
                messages=messages,
                toolConfig=TOOL_CONFIG,
                inferenceConfig={
                    "maxTokens": 2048,
                    "temperature": 0.0,
                    "topP": 0.1,
                },
            )

            stop_reason = response["stopReason"]
            assistant_message = response["output"]["message"]

            logger.info("[LangGraph] LLM stop_reason: %s", stop_reason)

            # Always add assistant message to history
            messages.append({"role": "assistant", "content": assistant_message["content"]})

            if stop_reason == "end_turn":
                # LLM is done — extract final text, stripping <thinking> blocks
                raw_text = ""
                for block in assistant_message["content"]:
                    if "text" in block:
                        raw_text += block["text"]
                final_text = _extract_json_from_text(raw_text)
                logger.info("[LangGraph] LLM end_turn — final recommendation ready")
                return final_text, coi_result

            elif stop_reason == "tool_use":
                # LLM wants to call a tool
                tool_results = []

                for block in assistant_message["content"]:
                    if "toolUse" not in block:
                        continue

                    tool_use = block["toolUse"]
                    tool_name = tool_use["name"]
                    tool_input = tool_use["input"]
                    tool_use_id = tool_use["toolUseId"]

                    logger.info(
                        "[LangGraph] LLM decided to call tool: %s with input: %s",
                        tool_name,
                        tool_input,
                    )

                    if tool_name == "check_conflicts":
                        # ── This is the A2A call to Strands ──
                        coi_result = await _call_strands_coi(
                            authors=tool_input["authors"],
                            candidate_editors=tool_input["candidate_editors"],
                        )
                        tool_result_text = json.dumps(coi_result, indent=2)
                        logger.info(
                            "[LangGraph] COI result — approved: %s | flagged: %s",
                            [e if isinstance(e, str) else e.get("editor") for e in coi_result.get("approved", [])],
                            [e if isinstance(e, str) else e.get("editor") for e in coi_result.get("flagged", [])],
                        )
                    else:
                        tool_result_text = json.dumps({"error": f"Unknown tool: {tool_name}"})

                    tool_results.append({
                        "toolResult": {
                            "toolUseId": tool_use_id,
                            "content": [{"text": tool_result_text}],
                        }
                    })

                # Feed tool results back to LLM
                messages.append({"role": "user", "content": tool_results})

            else:
                # Unexpected stop reason
                logger.warning("[LangGraph] Unexpected stop_reason: %s", stop_reason)
                break

    return "Error: ReAct loop ended unexpectedly", coi_result


# ─── JSON extraction helper ──────────────────────────────────────────────────

def _extract_json_from_text(text: str) -> str:
    """
    Strip <thinking>...</thinking> blocks and extract the first JSON object.
    Returns the raw text unchanged if no JSON object found.
    """
    # Remove <thinking>...</thinking> blocks (including nested)
    clean = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL).strip()
    # Remove markdown code fences
    clean = re.sub(r'```(?:json)?', '', clean).strip()
    # Find the first JSON object {...} in the remaining text
    match = re.search(r'(\{.*\})', clean, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
        try:
            json.loads(candidate)  # validate
            return candidate
        except json.JSONDecodeError:
            pass
    return clean or text


# ─── Mock ReAct (no Bedrock) ─────────────────────────────────────────────────

async def _run_react_mock(
    manuscript_info: str,
    available_editors: str,
) -> tuple[str, dict | None]:
    """
    Mock ReAct loop that still makes the real A2A COI call to Strands.
    Parses manuscript_info + available_editors to construct inputs, then
    calls _call_strands_coi, and builds a final recommendation from results.
    """
    logger.info("[LangGraph - MOCK] Starting mock ReAct loop")

    # ── Parse authors from manuscript_info ────────────────────────────────
    # Expected: "Authors: John Smith, Jane Doe, Robert Chen"
    authors: list[str] = []
    for line in manuscript_info.splitlines():
        if line.strip().lower().startswith("authors:"):
            raw = line.split(":", 1)[1]
            authors = [a.strip() for a in raw.split(",") if a.strip()]
            break
    logger.info("[LangGraph - MOCK] Authors: %s", authors)

    # ── Parse editor names from available_editors ─────────────────────────
    # Expected: "- Dr. Emily Jones (ID: ...) | ..."
    editor_names: list[str] = []
    editor_ids: dict[str, dict] = {}
    for line in available_editors.splitlines():
        stripped = line.strip().lstrip("-").strip()
        if not stripped:
            continue
        # Name is before the first "(" or "|"
        name = stripped.split("(")[0].split("|")[0].strip()
        if not name:
            continue
        # Extract PersonID
        person_id = ""
        if "PersonID:" in stripped:
            try:
                person_id = stripped.split("PersonID:")[1].split(")")[0].strip()
            except IndexError:
                pass
        # Extract ORCID (ID before comma)
        orcid = ""
        if "ID:" in stripped:
            try:
                orcid = stripped.split("ID:")[1].split(",")[0].strip()
            except IndexError:
                pass
        editor_names.append(name)
        editor_ids[name] = {"orcid": orcid, "person_id": person_id}

    logger.info("[LangGraph - MOCK] Candidate editors: %s", editor_names)

    # ── A2A call to Strands COI service ───────────────────────────────────
    logger.info("[LangGraph - MOCK] Calling Strands COI service via A2A")
    coi_result = await _call_strands_coi(
        authors=authors,
        candidate_editors=editor_names,
    )
    logger.info(
        "[LangGraph - MOCK] COI result — approved: %s | flagged: %s",
        coi_result.get("approved", []),
        coi_result.get("flagged", []),
    )

    # ── Build recommendation from COI result ──────────────────────────────
    approved = coi_result.get("approved", [])
    flagged = coi_result.get("flagged", [])
    runner_up = approved[1] if len(approved) > 1 else ""

    if approved:
        selected = approved[0]
        reasoning = (
            f"Selected '{selected}' as the best-matched editor with no conflicts of interest. "
            f"Flagged editors (COI): {[f.get('editor') if isinstance(f, dict) else f for f in flagged]}."
        )
    else:
        # All editors flagged — recommend override anyway (HITL will catch this)
        selected = flagged[0]["editor"] if flagged and isinstance(flagged[0], dict) else (flagged[0] if flagged else "")
        reasoning = "All candidate editors have conflicts. Escalation required."

    ids = editor_ids.get(selected, {})
    recommendation = {
        "selectedEditorName": selected,
        "selectedEditorOrcId": ids.get("orcid", ""),
        "selectedEditorPersonId": ids.get("person_id", ""),
        "reasoning": reasoning,
        "runnerUp": runner_up,
        "filteredOutEditors": [
            f.get("editor") if isinstance(f, dict) else f for f in flagged
        ],
    }

    final_text = json.dumps(recommendation)
    logger.info("[LangGraph - MOCK] Final recommendation: %s", final_text)
    return final_text, coi_result
