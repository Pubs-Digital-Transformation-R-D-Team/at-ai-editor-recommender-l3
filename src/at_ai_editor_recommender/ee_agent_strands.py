"""
Editor Assignment Workflow — AWS Strands Agents SDK implementation.

Replaces ee_graph_anthropic.py (LangGraph) with AWS Strands Agents SDK.

Architecture vs LangGraph:
──────────────────────────────────────────────────────────────────────────
  LangGraph                         Strands
  ─────────────────────────────     ─────────────────────────────────────
  Explicit graph (nodes + edges)    Model-driven agent loop
  AsyncAnthropicBedrock client      BedrockModel (native AWS)
  AsyncPostgresSaver (Tier 2)       S3SessionManager (session snapshot)
  AsyncPostgresStore (Tier 3)       Same Postgres store — wrapped as @tool
  6 checkpoint tables               1 S3 object per manuscript run
──────────────────────────────────────────────────────────────────────────

Workflow (Strands model-driven):
  1. LLM calls fetch_manuscript_data() tool
  2. LLM calls search_past_assignments() tool
  3. LLM reasons → produces JSON recommendation (no tool needed)
  4. Python: parse JSON → save to Postgres store → call assign API

Session Memory (Tier 2):
  S3SessionManager saves a snapshot after each agent invocation.
  Env var: S3_SESSIONS_BUCKET — if not set, runs without session persistence.

Long-term Memory (Tier 3):
  Same AsyncPostgresStore as before. save/search/format functions unchanged.
  The learning loop (Feb 24 → Feb 26) is fully preserved.
"""

import os
import json
import logging
import asyncio
import aiohttp
from dataclasses import dataclass
from typing import Optional

from strands import Agent, tool
from strands.models import BedrockModel

from at_ai_editor_recommender.editor_assignment_json_parser import EditorAssignmentJsonParser
from at_ai_editor_recommender.ee_api_adapter import get_adapter_for_url
from at_ai_editor_recommender.memory import (
    save_assignment_to_memory,
    search_similar_assignments,
    format_past_assignments_for_prompt,
)

logger = logging.getLogger(__name__)

REGION_NAME = os.getenv("AWS_REGION", "us-east-1")


# ── Data model (same as ee_graph_anthropic.py — shared by app.py) ─────────────

@dataclass
class ManuscriptSubmission:
    manuscript_number: str
    journal_id: str
    is_resubmit: bool


# ═══════════════════════════════════════════════════════════════════════════════
#  STRANDS AGENT — Editor Assignment
# ═══════════════════════════════════════════════════════════════════════════════

class EditorAssignmentAgent:
    """
    Strands-based editor assignment agent.

    Replaces EditorAssignmentWorkflow (LangGraph) from ee_graph_anthropic.py.
    Drop-in replacement: same constructor signature (minus `checkpointer`),
    same async_execute_workflow() entry point, same return dict structure.

    Usage:
        agent = EditorAssignmentAgent(store=store, model_id=MODEL_ID)
        result = await agent.async_execute_workflow(manuscript_submission)
    """

    DEFAULT_MODEL_ID = "us.amazon.nova-premier-v1:0"

    def __init__(self, store=None, model_id=DEFAULT_MODEL_ID, region_name=REGION_NAME,
                 checkpointer=None):
        # checkpointer arg accepted but ignored — Strands uses S3SessionManager instead
        self.logger = logging.getLogger(self.__class__.__name__)
        self._store = store
        self._model_id = model_id
        self._region_name = region_name
        self._ee_url = os.getenv("EE_URL")
        self._assign_url = os.getenv("ASSIGN_URL")
        self._validate_url = os.getenv("VALIDATE_ASSIGNMENT_URL")

        # BedrockModel uses the same IRSA credentials as before (no changes to K8s)
        self._bedrock_model = BedrockModel(
            model_id=model_id,
            region_name=region_name,
        )

        self.logger.info("EditorAssignmentAgent initialized. model=%s region=%s", model_id, region_name)
        if store:
            self.logger.info("Long-term Memory (Postgres store) is ENABLED")
        if os.getenv("S3_SESSIONS_BUCKET"):
            self.logger.info("Session Memory (S3SessionManager) is ENABLED — bucket=%s",
                             os.getenv("S3_SESSIONS_BUCKET"))
        else:
            self.logger.info("Session Memory: S3_SESSIONS_BUCKET not set — running without session persistence")

    # ── Private helpers ────────────────────────────────────────────────────────

    def _resolve_journal_specific_rules(self, journal_id: str) -> str:
        """Load journal-specific assignment rules (same logic as LangGraph version)."""
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
        prompts_root = os.path.join(project_root, "prompts")
        default_path = os.path.join(prompts_root, "journal_specific_rules", "DEFAULT.md")
        specific_path = os.path.join(prompts_root, "journal_specific_rules", f"{journal_id}.md")
        path = specific_path if os.path.exists(specific_path) else default_path
        with open(path, "r") as f:
            return f.read()

    async def _validate_existing_assignment(self, manuscript_number: str, journal_id: str) -> dict:
        """For resubmissions: check if a valid editor is already assigned."""
        if not self._validate_url:
            raise RuntimeError("VALIDATE_ASSIGNMENT_URL env var not set")

        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field("manuscript_id", manuscript_number)
            form_data.add_field("journal_id", journal_id)
            async with session.post(self._validate_url, data=form_data) as resp:
                resp.raise_for_status()
                api_response = await resp.json()
                self.logger.info("Validation API response: %s", api_response)

        return {
            "is_assignment_valid": api_response.get("data", {}).get("valid", False),
            "existing_assigned_editor": api_response.get("data", {}).get("editorId", ""),
        }

    async def _call_assign_api(self, manuscript_number: str, journal_id: str,
                               editor_person_id: str, llm_output: str = "") -> None:
        """Call the EE assign API to assign the selected editor."""
        if not self._assign_url:
            raise RuntimeError("ASSIGN_URL env var not set")

        self.logger.info("Calling assign API: editor=%s manuscript=%s", editor_person_id, manuscript_number)

        async with aiohttp.ClientSession() as session:
            form_data = aiohttp.FormData()
            form_data.add_field("manuscript_id", manuscript_number)
            form_data.add_field("journal_id", journal_id)
            form_data.add_field("editor_id", editor_person_id)
            async with session.post(self._assign_url, data=form_data) as resp:
                try:
                    resp.raise_for_status()
                    self.logger.info("Assign API success: editor %s → %s", editor_person_id, manuscript_number)
                except aiohttp.ClientResponseError as e:
                    body = await resp.text()
                    # Attach LLM recommendation to error body (same pattern as LangGraph)
                    try:
                        body_data = json.loads(body)
                        if llm_output:
                            body_data["llm_response"] = EditorAssignmentJsonParser.parse(llm_output)
                        body = json.dumps(body_data)
                    except Exception:
                        pass
                    e.response_text = body
                    raise

    async def _save_to_long_term_memory(self, manuscript_submission: ManuscriptSubmission,
                                        llm_response: dict) -> None:
        """
        Save editor assignment decision to Tier 3 long-term Postgres store.
        Called BEFORE the assign API — same pattern as LangGraph version.
        """
        if not self._store:
            return
        try:
            memory_state = {
                "manuscript_submission": manuscript_submission,
                "editor_id": llm_response.get("selectedEditorOrcId", ""),
                "editor_person_id": llm_response.get("selectedEditorPersonId", ""),
                "reasoning": llm_response.get("reasoning", ""),
                "runner_up": llm_response.get("runnerUp", ""),
                "filtered_out_editors": llm_response.get("filteredOutEditors", ""),
            }
            self.logger.info("Long-term Memory: saving assignment for %s",
                             manuscript_submission.manuscript_number)
            await save_assignment_to_memory(self._store, memory_state)
        except Exception as e:
            # Never let memory saves break the main workflow
            self.logger.warning("Long-term Memory save failed (continuing): %s", e)

    def _build_tools(self, manuscript_submission: ManuscriptSubmission) -> list:
        """
        Build @tool-decorated functions for this manuscript request.

        Uses closures to capture per-request context (store, ee_url, manuscript info).
        Each request gets its own fresh tool instances — no shared state conflicts.

        Tools the LLM can call:
          1. fetch_manuscript_data()       — gets manuscript + editors from EE API
          2. search_past_assignments(query) — searches Tier 3 Postgres store
        """
        store = self._store
        ee_url = self._ee_url
        journal_id = manuscript_submission.journal_id
        manuscript_number = manuscript_submission.manuscript_number

        @tool
        async def fetch_manuscript_data() -> str:
            """
            Fetch manuscript information and the list of available editors from the EE API.
            ALWAYS call this tool first before making any recommendation.
            Returns manuscript details (title, abstract, authors, institutions) and
            the full list of available editors with their workload-expertise ranks.
            """
            adapter = get_adapter_for_url(ee_url)
            result = await adapter.get_manuscript_with_editors(manuscript_number, journal_id)
            manuscript_info = result.get("manuscript_information", "")
            available_editors = result.get("available_editors", "")
            logger.info("Fetched manuscript data for %s", manuscript_number)
            return (
                f"MANUSCRIPT INFORMATION:\n{manuscript_info}\n\n"
                f"AVAILABLE EDITORS:\n{available_editors}"
            )

        @tool
        async def search_past_assignments(query: str) -> str:
            """
            Search long-term memory for past editor assignments similar to this manuscript.
            Call this AFTER fetch_manuscript_data, using the manuscript title and abstract as the query.
            Returns past assignment records showing which editors were selected for similar manuscripts.
            Use these as REFERENCE ONLY — evaluate the current manuscript on its own merits.

            Args:
                query: The manuscript title and abstract text to search for similar past assignments.
            """
            if not store:
                return "Long-term memory not configured. No past assignments available."

            results = await search_similar_assignments(
                store,
                query=query,
                journal_id=journal_id,
                limit=5,
            )
            formatted = format_past_assignments_for_prompt(results)
            if formatted:
                logger.info("Long-term Memory: found %d similar past assignments for %s",
                            len(results), manuscript_number)
                return formatted
            logger.info("Long-term Memory: no similar past assignments found for %s", manuscript_number)
            return "No similar past assignments found in memory for this journal."

        return [fetch_manuscript_data, search_past_assignments]

    def _build_system_prompt(self, journal_id: str) -> str:
        """
        Build the Strands agent system prompt.

        Embeds:
          - Journal-specific assignment rules
          - Global Path A/B/C rules (from V3 prompt)
          - Step-by-step tool usage instructions
          - Required JSON output format
        """
        rules = self._resolve_journal_specific_rules(journal_id)

        return f"""You are an expert editor assignment agent for a scientific journal publisher.
Your job is to assign the most suitable editor to a manuscript submission.

## Your Steps (follow in this EXACT order):

STEP 1: Call fetch_manuscript_data to get the manuscript details and available editors list.

STEP 2: Call search_past_assignments using the manuscript title and abstract as the query,
        to check if similar manuscripts have been assigned before.

STEP 3: Apply the assignment rules below to select the best editor from the available list.

STEP 4: Return ONLY a valid JSON object in the exact format specified below. No other text.

---

## Assignment Rules

### STEP 1 of Rules: Eligibility Check (COI Filtering)

Remove editors whose institution matches ANY author institution:

MATCHES (COI):
- Known abbreviations: MIT is same as Massachusetts Institute of Technology
- Same university, any campus: UC Berkeley is same as University of California, Berkeley
- Minor spelling variations of SAME institution

NOT MATCHES (no COI):
- Parent/child orgs: Harvard Medical School is not same as Harvard University
- Similar names: Global Research Lab is not same as Global Research Laboratory
- Affiliations: Google DeepMind is not same as Google/Alphabet

Process:
1. Compare each editor institution vs ALL author institutions
2. >90% confidence required for COI
3. Remove ONLY editors with confirmed COI
4. When uncertain: NO COI

Proceed with all non-COI editors.

---

### STEP 2 of Rules: Choose Exactly ONE Assignment Path

## PATH A: Journal-Specific Rules
{rules}

## PATH B: Global Rules for Non-Peer-Reviewed Administrative Manuscripts
Use PATH B ONLY if BOTH of these are true:
- Is Manuscript Peer-Reviewed = "No"
- Manuscript Type is EXACTLY one of:
  Additions and Corrections, Announcement, Correspondence/Rebuttal, Center Stage,
  Editorial, Expression of Concern, First Reactions, The Hub, Retraction, Viewpoint

If both apply, assign as follows:
1. Assign to the Deputy Editor, if any Deputy Editor exists.
2. If no Deputy Editor, assign to the Editor-in-Chief, if any exists.
3. If neither exists, leave selectedEditor empty.
If PATH B applies but no eligible editor is available, do not make an assignment.
If PATH B does NOT apply, you MUST use PATH C.

## PATH C: Standard Assignment (MANDATORY if A and B do not apply)
PATH C AUTOMATICALLY APPLIES TO EVERYTHING NOT HANDLED BY A OR B.

RULE: MUST SELECT EDITOR WITH LOWEST RANK NUMBER.
EDITORS WITH RANK NA ARE NOT ELIGIBLE FOR PATH C.

ALGORITHM:
- PATH C IGNORES EVERYTHING EXCEPT RANK
- Editor role: IRRELEVANT
- Manuscript type: IRRELEVANT
- Peer-review status: IRRELEVANT
- ONLY RANK MATTERS: 1 is best, 2 is second best, etc.

VIOLATIONS:
1. Not selecting an editor when editors exist
2. Selecting higher rank when lower exists
3. Considering anything besides rank
4. Considering editors with rank NA

MANDATORY: If PATH C applies and editors exist, MUST assign to lowest rank.

---

## Output Format

CRITICAL: Return ONLY valid JSON — no additional text, explanations, or markdown.
Before returning, verify that selectedEditorOrcId and selectedEditorPersonId match
the actual editor chosen in your reasoning.

{{
  "selectedEditorOrcId": "editor's ORCID or empty-string",
  "selectedEditorPersonId": "editor's personId or empty-string",
  "reasoning": "Brief 2-3 sentence explanation of decision",
  "runnerUp": "Note on runner-up if applicable (e.g., 'Editor X with reasoning')",
  "filteredOutEditors": "List of filtered editor IDs with reasons"
}}"""

    def _build_session_manager(self, session_id: str):
        """
        Create an S3SessionManager for this manuscript run.

        Strands Tier 2 memory: saves conversation + state snapshot to S3 after
        each agent invocation. If pod restarts, agent reloads session from S3.

        Returns None if S3_SESSIONS_BUCKET is not configured (graceful degradation).
        """
        s3_bucket = os.getenv("S3_SESSIONS_BUCKET")
        if not s3_bucket:
            return None

        try:
            # Import here so missing strands[s3] doesn't break startup
            from strands.session.s3_session_manager import S3SessionManager
            sm = S3SessionManager(
                session_id=session_id,
                bucket=s3_bucket,
                region_name=self._region_name,
            )
            self.logger.info("S3SessionManager created: bucket=%s session_id=%s", s3_bucket, session_id)
            return sm
        except Exception as e:
            self.logger.warning("S3SessionManager init failed (running without session): %s", e)
            return None

    # ── Main entry point ───────────────────────────────────────────────────────

    async def async_execute_workflow(self, manuscript_submission: ManuscriptSubmission) -> dict:
        """
        Run the full editor assignment workflow using AWS Strands.

        Flow:
          1. Resubmission check (Python — deterministic, no LLM needed)
          2. Build Strands Agent with tools + S3SessionManager
          3. Agent: fetch data → search memory → produce JSON recommendation
          4. Python: parse JSON → save to Tier 3 memory → call assign API
          5. Return result dict (same structure as LangGraph version)

        Returns:
            dict with: editor_id, editor_person_id, assignment_result,
                       reasoning, runner_up, filtered_out_editors
        """
        ms = manuscript_submission
        self.logger.info("Strands workflow starting for %s (journal=%s resubmit=%s)",
                         ms.manuscript_number, ms.journal_id, ms.is_resubmit)

        # ── Resubmission: check existing assignment first (no LLM needed) ────
        if ms.is_resubmit:
            self.logger.info("Resubmission detected — validating existing assignment")
            validation = await self._validate_existing_assignment(ms.manuscript_number, ms.journal_id)
            if validation["is_assignment_valid"]:
                existing_editor = validation["existing_assigned_editor"]
                self.logger.info("Valid existing assignment found: editor=%s", existing_editor)
                return {
                    "editor_id": "",
                    "editor_person_id": existing_editor,
                    "assignment_result": (
                        f"Valid editor is already assigned to manuscript_number: "
                        f"{ms.manuscript_number}, editor_id: {existing_editor}"
                    ),
                    "reasoning": "Manuscript is a resubmission with valid existing editor assignment",
                    "runner_up": "",
                    "filtered_out_editors": "",
                }
            self.logger.info("Resubmission has no valid assignment — proceeding with normal flow")

        # ── Build Strands Agent for this request ──────────────────────────────
        session_id = f"{ms.journal_id}-{ms.manuscript_number}"
        session_manager = self._build_session_manager(session_id)
        tools = self._build_tools(ms)
        system_prompt = self._build_system_prompt(ms.journal_id)

        agent = Agent(
            model=self._bedrock_model,
            system_prompt=system_prompt,
            tools=tools,
            session_manager=session_manager,
        )

        # ── Run Agent (async — Strands supports invoke_async) ─────────────────
        task = (
            f"Assign an editor to manuscript {ms.manuscript_number} "
            f"for journal {ms.journal_id}. "
            f"Is resubmission: {ms.is_resubmit}. "
            f"Follow your steps: call fetch_manuscript_data first, "
            f"then search_past_assignments with the manuscript abstract as query, "
            f"then produce the JSON recommendation."
        )

        self.logger.info("Running Strands agent for %s", ms.manuscript_number)

        if os.getenv("MOCK_LLM_RESPONSE", "false").lower() == "true":
            # Fast path for testing — skip agent entirely
            import asyncio as _asyncio
            delay = float(os.getenv("MOCK_LLM_DELAY", "0"))
            if delay > 0:
                await _asyncio.sleep(delay / 1_000)
            llm_output = json.dumps({
                "selectedEditorOrcId": "1234",
                "selectedEditorPersonId": "1234",
                "reasoning": "Mock LLM is enabled, so this is a mock response.",
                "runnerUp": "No runner-up — mock response",
                "filteredOutEditors": "None filtered — mock response",
            })
        else:
            agent_result = await agent.invoke_async(task)
            llm_output = str(agent_result)
            self.logger.info("Agent completed for %s", ms.manuscript_number)

        # ── Parse LLM recommendation ──────────────────────────────────────────
        parsed = EditorAssignmentJsonParser.parse(llm_output)
        self.logger.info("Parsed recommendation for %s: editor=%s",
                         ms.manuscript_number, parsed.get("selectedEditorPersonId", ""))

        editor_person_id = parsed.get("selectedEditorPersonId", "")
        editor_orcid = parsed.get("selectedEditorOrcId", "")
        reasoning = parsed.get("reasoning", "")
        runner_up = parsed.get("runnerUp", "")
        filtered_out = parsed.get("filteredOutEditors", "")

        # ── Tier 3: Save to long-term memory BEFORE calling assign API ────────
        # (same order as LangGraph — data preserved even if assign API fails)
        await self._save_to_long_term_memory(ms, parsed)

        # ── Call assign API ───────────────────────────────────────────────────
        if editor_person_id:
            await self._call_assign_api(
                ms.manuscript_number,
                ms.journal_id,
                editor_person_id,
                llm_output=llm_output,
            )
            assignment_result = (
                f"Editor with editor_id of {editor_person_id} assigned to "
                f"manuscript_number: {ms.manuscript_number}"
            )
        else:
            assignment_result = f"No editor assigned to manuscript_number: {ms.manuscript_number}"

        self.logger.info("Strands workflow complete for %s: %s", ms.manuscript_number, assignment_result)

        return {
            "editor_id": editor_orcid,
            "editor_person_id": editor_person_id,
            "assignment_result": assignment_result,
            "reasoning": reasoning,
            "runner_up": runner_up,
            "filtered_out_editors": filtered_out,
        }
