"""
Strands Travel Planner Agent.
─────────────────────────────
Uses Bedrock Nova with 7 tools (4 memory + 3 planning).
The agent reads L3 memory, reasons over it, and plans personalised trips.
"""

import logging
import os

from dotenv import load_dotenv
from strands import Agent
from strands.models import BedrockModel

from tools import ALL_TOOLS

load_dotenv()
logger = logging.getLogger(__name__)

MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.amazon.nova-premier-v1:0")
REGION = os.getenv("AWS_DEFAULT_REGION", "us-east-1")

SYSTEM_PROMPT = """\
You are a personal AI travel planner with persistent memory.

━━━ MANDATORY FIRST STEPS (every time) ━━━
1. Call get_preferences() — load the traveler's profile from long-term memory.
2. Call search_past_trips() with a relevant keyword to find past travel history.
3. Use this context to PERSONALISE every suggestion.

━━━ PLANNING ━━━
• Call search_hotels() filtered by known preferences (type, budget).
• Call search_activities() filtered by activity_preference and crowd tolerance.
• Call get_weather() for the destination and travel month.
• Reference past trips: "You loved X in Lisbon, so try Y here."
• Warn about things the traveler disliked before.

━━━ AFTER PLANNING ━━━
• When the user rates a trip, call save_trip_to_memory().
• When you learn a new preference, call save_user_preference().

━━━ TRANSPARENCY ━━━
Always say WHAT memory you used: "Based on your preference for boutique hotels…"

Be friendly, concise, and enthusiastic about travel.
"""


def build_agent() -> Agent:
    """Build and return the Strands travel planner agent."""
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
    agent = Agent(model=model, tools=ALL_TOOLS, system_prompt=SYSTEM_PROMPT)
    logger.info("Strands agent ready (model=%s, tools=%d)", MODEL_ID, len(ALL_TOOLS))
    return agent

