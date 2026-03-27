"""
A2A Agent Card — LangGraph Editor Recommender
──────────────────────────────────────────────
Defines the AgentCard that this service advertises at
``GET /.well-known/agent.json``.

The card tells other A2A agents (e.g. the Strands COI specialist)
what skills this agent offers and how to reach it.
"""

import os

from a2a.types import (
    AgentCard,
    AgentCapabilities,
    AgentSkill,
)

AGENT_CARD = AgentCard(
    name="Editor Recommender (LangGraph)",
    description=(
        "Assigns peer-review editors to manuscripts. "
        "Also provides editor publication history for COI checks."
    ),
    url=os.getenv("AGENT_CARD_URL", "http://localhost:8000"),
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
