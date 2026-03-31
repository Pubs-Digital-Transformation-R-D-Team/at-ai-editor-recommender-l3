"""
Strands Agent — editor assignment with L3 memory.

Tools:
  fetch_manuscript_data()     → EE API (manuscript + editors)
  search_past_assignments()   → L3 READ (Postgres)

Flow: fetch → search memory → LLM recommends → save to L3 → call assign API
"""

import json
import logging
import os
import re
from dataclasses import dataclass

from strands import Agent, tool
from strands.models import BedrockModel

from memory import save_assignment, search_assignments, format_for_prompt

logger = logging.getLogger(__name__)


@dataclass
class ManuscriptSubmission:
    manuscript_number: str
    journal_id: str
    is_resubmit: bool = False


class EditorAssignmentAgent:

    def __init__(self, store=None, model_id="us.amazon.nova-premier-v1:0"):
        self._store = store
        self._model = BedrockModel(
            model_id=model_id,
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )
        self._ee_url = os.getenv("EE_URL")
        self._assign_url = os.getenv("ASSIGN_URL")

    def _build_tools(self, ms: ManuscriptSubmission):
        store, ee_url, journal = self._store, self._ee_url, ms.journal_id

        @tool
        async def fetch_manuscript_data() -> str:
            """Fetch manuscript + editors from EE API. Call FIRST."""
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.post(ee_url, data={
                    "manuscript_id": ms.manuscript_number,
                    "journal_id": journal,
                }) as r:
                    r.raise_for_status()
                    return await r.text()

        @tool
        async def search_past_assignments(query: str) -> str:
            """Search L3 memory for similar past assignments.
            Args: query: manuscript title + abstract"""
            if not store:
                return "No memory configured."
            results = await search_assignments(store, query, journal_id=journal, limit=5)
            return format_for_prompt(results) or "No past assignments found."

        return [fetch_manuscript_data, search_past_assignments]

    async def execute(self, ms: ManuscriptSubmission) -> dict:
        """Run full assignment workflow."""
        logger.info("Starting: %s (journal=%s)", ms.manuscript_number, ms.journal_id)

        # Mock path for testing
        if os.getenv("MOCK_LLM_RESPONSE", "").lower() == "true":
            parsed = {
                "selectedEditorOrcId": "mock-orcid",
                "selectedEditorPersonId": "mock-person",
                "reasoning": "Mock LLM response for testing",
                "runnerUp": "", "filteredOutEditors": "",
            }
        else:
            agent = Agent(
                model=self._model,
                system_prompt=self._build_prompt(ms.journal_id),
                tools=self._build_tools(ms),
            )
            raw = str(await agent.invoke_async(
                f"Assign editor to {ms.manuscript_number} for {ms.journal_id}."
            ))
            match = re.search(r"(\{.*\})", raw, re.DOTALL)
            parsed = json.loads(match.group(1) if match else raw)

        editor = parsed.get("selectedEditorPersonId", "")

        # L3 WRITE — save BEFORE assign API
        if self._store:
            await save_assignment(self._store, {
                "manuscript_submission": ms,
                "editor_person_id": editor,
                "reasoning": parsed.get("reasoning", ""),
                "runner_up": parsed.get("runnerUp", ""),
                "filtered_out_editors": parsed.get("filteredOutEditors", ""),
            })

        return {
            "editor_person_id": editor,
            "reasoning": parsed.get("reasoning", ""),
            "runner_up": parsed.get("runnerUp", ""),
            "filtered_out_editors": parsed.get("filteredOutEditors", ""),
        }

    def _build_prompt(self, journal_id):
        return """You are an editor assignment agent.
Steps: 1) fetch_manuscript_data  2) search_past_assignments  3) Return JSON.
Output only: {"selectedEditorOrcId":"..","selectedEditorPersonId":"..","reasoning":"..","runnerUp":"..","filteredOutEditors":".."}"""

