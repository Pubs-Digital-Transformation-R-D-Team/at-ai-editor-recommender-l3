"""
A2A Agent Card — Strands COI Checker
────────────────────────────────────
Defines the AgentCard that this service advertises at
``GET /.well-known/agent.json``.

The card tells other A2A agents (e.g. the LangGraph orchestrator)
that this agent can check conflicts of interest between manuscript
authors and candidate editors.
"""

import os

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
)

AGENT_CARD = AgentCard(
    name="COI Checker (Strands)",
    description=(
        "Checks conflict of interest between manuscript authors and candidate "
        "editors.  Fetches editor publication history from the Editor "
        "Recommender service and identifies co-authorship/collaboration "
        "conflicts."
    ),
    url=os.getenv("AGENT_CARD_URL", "http://localhost:8001"),
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
