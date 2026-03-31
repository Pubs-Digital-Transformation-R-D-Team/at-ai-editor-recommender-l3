"""
Smart Calculator — LangGraph Version
─────────────────────────────────────
Same tools, same prompt as the Strands version.
Notice the additional boilerplate: state schema, graph nodes, edges, compilation.

Usage:
    python langgraph_calc.py "What is (15 * 4) + sqrt(144) - 8?"
    python langgraph_calc.py   # interactive mode
"""

import json
import math
import sys
from typing import Annotated, TypedDict

from langchain_aws import ChatBedrock
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages


# ── Tools (must return strings for LangChain) ───────────────────────────────

@lc_tool
def add(a: float, b: float) -> str:
    """Add two numbers. Use this for addition operations."""
    return str(a + b)


@lc_tool
def subtract(a: float, b: float) -> str:
    """Subtract b from a. Use this for subtraction operations."""
    return str(a - b)


@lc_tool
def multiply(a: float, b: float) -> str:
    """Multiply two numbers. Use this for multiplication operations."""
    return str(a * b)


@lc_tool
def divide(a: float, b: float) -> str:
    """Divide a by b. Use this for division operations."""
    if b == 0:
        return str(float("inf"))
    return str(a / b)


@lc_tool
def power(base: float, exponent: float) -> str:
    """Raise base to the power of exponent."""
    return str(base ** exponent)


@lc_tool
def sqrt(n: float) -> str:
    """Calculate the square root of a number."""
    return str(math.sqrt(n))


# ── Tool registry (LangGraph requires manual dispatch) ──────────────────────

TOOLS = [add, subtract, multiply, divide, power, sqrt]
TOOL_MAP = {t.name: t for t in TOOLS}


# ── State schema (LangGraph requires explicit state definition) ──────────────

class CalcState(TypedDict):
    messages: Annotated[list, add_messages]


# ── LLM with tools bound ────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a calculator assistant. Use the provided math tools to solve "
    "problems step by step. Always use tools for calculations — never do "
    "mental math. Show your work, then give the final answer."
)

llm = ChatBedrock(
    model_id="us.amazon.nova-premier-v1:0",
    region_name="us-east-1",
)
llm_with_tools = llm.bind_tools(TOOLS)


# ── Graph nodes ──────────────────────────────────────────────────────────────

def agent_node(state: CalcState) -> CalcState:
    """Call the LLM with the current message history."""
    messages = state["messages"]
    response = llm_with_tools.invoke(
        [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    )
    return {"messages": [response]}


def tool_node(state: CalcState) -> CalcState:
    """Execute any tool calls from the last AI message."""
    last_message = state["messages"][-1]
    tool_results = []

    for tool_call in last_message.tool_calls:
        tool_fn = TOOL_MAP[tool_call["name"]]
        result = tool_fn.invoke(tool_call["args"])
        tool_results.append(
            ToolMessage(
                content=str(result),
                tool_call_id=tool_call["id"],
            )
        )

    return {"messages": tool_results}


# ── Conditional edge (LangGraph requires explicit routing logic) ─────────────

def should_continue(state: CalcState) -> str:
    """Route: if the LLM made tool calls → 'tools', else → END."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# ── Build the graph ──────────────────────────────────────────────────────────

graph = StateGraph(CalcState)

# Add nodes
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)

# Add edges
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")

# Compile
calculator = graph.compile()


# ── Entry point ──────────────────────────────────────────────────────────────

def ask(question: str) -> str:
    """Send a question through the graph and return the final answer."""
    result = calculator.invoke(
        {"messages": [HumanMessage(content=question)]}
    )
    return result["messages"][-1].content


if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"\n📝 Question: {question}\n")
        answer = ask(question)
        print(f"\n✅ Answer: {answer}")
    else:
        print("🧮 LangGraph Smart Calculator (type 'quit' to exit)\n")
        while True:
            question = input("❓ Enter math problem: ").strip()
            if question.lower() in ("quit", "exit", "q"):
                break
            if not question:
                continue
            answer = ask(question)
            print(f"\n✅ Answer: {answer}\n")
