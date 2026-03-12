"""
POC Runner — L3 + A2A + HITL Demo
────────────────────────────────────
Starts:
  - LangGraph callback server  (port 8000)  — serves editor history to Strands
  - Strands COI service        (port 8001)  — performs COI checks via A2A

Then runs the LangGraph graph directly to:
  1. Load manuscript MS-999
  2. Run ReAct loop → LLM calls check_conflicts → A2A to Strands
  3. Strands calls back to LangGraph for editor history → A2A callback
  4. COI result returned → if conflict found → HITL interrupt
  5. Human decides → graph resumes → final assignment

Usage:
  python run_poc.py

Requirements:
  pip install -r poc/requirements.txt
  AWS credentials must be configured (Bedrock access in us-east-1)
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time

import httpx
from langgraph.types import Command

# ─── Setup paths ────────────────────────────────────────────────────────────

POC_DIR = os.path.dirname(__file__)
sys.path.insert(0, POC_DIR)

from langgraph_service.graph import build_graph  # noqa: E402

# ─── Logging ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
logger = logging.getLogger(__name__)

BANNER = "═" * 70


# ─── Server management ───────────────────────────────────────────────────────

def start_server(script_path: str, name: str) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, script_path],
        env={**os.environ, "PYTHONPATH": POC_DIR},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    logger.info("Started %s (pid=%d)", name, proc.pid)
    return proc


async def wait_for_server(url: str, name: str, timeout: int = 30):
    logger.info("Waiting for %s to be ready at %s ...", name, url)
    start = time.time()
    async with httpx.AsyncClient() as client:
        while time.time() - start < timeout:
            try:
                r = await client.get(url, timeout=2.0)
                if r.status_code == 200:
                    logger.info("✓ %s is ready", name)
                    return
            except Exception:
                pass
            await asyncio.sleep(1.0)
    raise TimeoutError(f"{name} did not start within {timeout}s")


# ─── HITL prompt ─────────────────────────────────────────────────────────────

def prompt_human(interrupt_data: dict) -> str:
    print()
    print(BANNER)
    print(interrupt_data.get("message", "HUMAN INPUT REQUIRED"))
    print(BANNER)
    print()
    print("FLAGGED EDITORS:")
    print(interrupt_data.get("flagged_editors", "  (none listed)"))
    print()
    approved = interrupt_data.get("approved_alternatives", [])
    print(f"APPROVED ALTERNATIVES: {', '.join(approved) if approved else 'none'}")
    print()
    options = interrupt_data.get("options", {})
    print("OPTIONS:")
    for key, val in options.items():
        print(f"  {key}. {val}")
    print()

    while True:
        choice = input("Your choice: ").strip()
        if choice in options:
            print(f"\n✓ You selected option {choice}: {options[choice]}")
            return choice
        print(f"  Please enter one of: {list(options.keys())}")


# ─── Main flow ───────────────────────────────────────────────────────────────

async def run_poc():
    print()
    print(BANNER)
    print("  POC: L3 Multi-Agent Orchestration — LangGraph ↔ Strands via A2A")
    print(BANNER)

    # ── Step 1: Start background servers ─────────────────────────────────────
    print("\n[1/5] Starting background services...")

    lg_server = start_server(
        os.path.join(POC_DIR, "langgraph_service", "callback_server.py"),
        "LangGraph callback server",
    )
    st_server = start_server(
        os.path.join(POC_DIR, "strands_service", "server.py"),
        "Strands COI server",
    )

    try:
        await wait_for_server("http://localhost:8000/.well-known/agent.json", "LangGraph:8000")
        await wait_for_server("http://localhost:8001/.well-known/agent.json", "Strands:8001")

        # ── Step 2: Discover Agent Cards ──────────────────────────────────────
        print("\n[2/5] Discovering Agent Cards (A2A)...")
        async with httpx.AsyncClient() as client:
            lg_card = (await client.get("http://localhost:8000/.well-known/agent.json")).json()
            st_card = (await client.get("http://localhost:8001/.well-known/agent.json")).json()

        print(f"  ✓ LangGraph Agent: '{lg_card['name']}'")
        print(f"    Skills: {[s['id'] for s in lg_card['skills']]}")
        print(f"  ✓ Strands Agent:   '{st_card['name']}'")
        print(f"    Skills: {[s['id'] for s in st_card['skills']]}")

        # ── Step 3: Build graph ───────────────────────────────────────────────
        print("\n[3/5] Building LangGraph StateGraph...")
        graph, config = build_graph()
        print("  ✓ Graph compiled with MemorySaver checkpointer (HITL-ready)")

        # ── Step 4: Run the graph ─────────────────────────────────────────────
        print("\n[4/5] Starting editor assignment for manuscript MS-999...")
        print(f"      {'─' * 60}")

        initial_state = {"manuscript_number": "MS-999"}
        final_state = None
        human_decision = None

        # Stream updates so we can detect interrupt
        async for event in graph.astream(
            initial_state, config=config, stream_mode="updates"
        ):
            # Check for HITL interrupt
            if "__interrupt__" in event:
                interrupts = event["__interrupt__"]
                interrupt_value = interrupts[0].value if interrupts else {}

                print(f"\n{'─' * 70}")
                print("  [LangGraph] ⚑ Graph PAUSED — interrupt() raised in coi_review node")
                print("  [LangGraph] State saved to MemorySaver checkpointer")
                print(f"{'─' * 70}")

                # HITL — ask the human
                human_decision = prompt_human(interrupt_value)

                # Resume the graph
                print("\n[4/5 cont.] Resuming graph with human decision...")
                async for resumed_event in graph.astream(
                    Command(resume=human_decision),
                    config=config,
                    stream_mode="updates",
                ):
                    for node_name, node_output in resumed_event.items():
                        if node_name == "__interrupt__":
                            continue
                        if isinstance(node_output, dict) and "final_assignment" in node_output:
                            final_state = node_output
                        logger.info("  [Graph] Node '%s' completed", node_name)
                break

            # Normal node completion
            for node_name, node_output in event.items():
                if node_name == "__interrupt__":
                    continue
                logger.info("  [Graph] Node '%s' completed", node_name)
                if isinstance(node_output, dict) and "final_assignment" in node_output:
                    final_state = node_output

        # ── Step 5: Print result ──────────────────────────────────────────────
        print(f"\n[5/5] Final Result")
        print(BANNER)

        if not final_state or "final_assignment" not in final_state:
            # Get the full state snapshot
            snapshot = graph.get_state(config)
            final_state = snapshot.values

        assignment = (
            final_state.get("final_assignment", {})
            if isinstance(final_state, dict)
            else {}
        )

        rec = assignment.get("recommendation", {})
        coi = assignment.get("coi_result", {})

        print(f"  Manuscript:       MS-999")
        print(f"  Assigned Editor:  {rec.get('selectedEditorName', rec.get('raw_output', 'see below'))}")
        print(f"  OrcID:            {rec.get('selectedEditorOrcId', 'N/A')}")
        print(f"  Reasoning:        {rec.get('reasoning', 'N/A')[:120]}")
        print(f"  Runner-Up:        {rec.get('runnerUp', 'N/A')}")
        if coi:
            approved = [e if isinstance(e, str) else e.get("editor") for e in coi.get("approved", [])]
            flagged = [e if isinstance(e, str) else e.get("editor") for e in coi.get("flagged", [])]
            print(f"  COI Approved:     {approved}")
            print(f"  COI Flagged:      {flagged}")
        if human_decision:
            print(f"  Human Decision:   Option {human_decision}")
        if "override_note" in rec:
            print(f"  Override Note:    {rec['override_note']}")
        print(BANNER)
        print()

    finally:
        # Cleanup
        lg_server.terminate()
        st_server.terminate()
        logger.info("Background servers stopped")


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(run_poc())
