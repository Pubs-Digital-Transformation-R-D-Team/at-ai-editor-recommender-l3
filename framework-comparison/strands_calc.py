"""
Smart Calculator — Strands Agent Version
─────────────────────────────────────────
Same tools, same prompt as the LangGraph version.
Notice how little code is needed.

Usage:
    python strands_calc.py "What is (15 * 4) + sqrt(144) - 8?"
    python strands_calc.py   # interactive mode
"""

import math
import sys

from strands import Agent, tool
from strands.models import BedrockModel


# ── Tools ────────────────────────────────────────────────────────────────────

@tool
def add(a: float, b: float) -> float:
    """Add two numbers. Use this for addition operations."""
    return a + b


@tool
def subtract(a: float, b: float) -> float:
    """Subtract b from a. Use this for subtraction operations."""
    return a - b


@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers. Use this for multiplication operations."""
    return a * b


@tool
def divide(a: float, b: float) -> float:
    """Divide a by b. Use this for division operations."""
    if b == 0:
        return float("inf")
    return a / b


@tool
def power(base: float, exponent: float) -> float:
    """Raise base to the power of exponent."""
    return base ** exponent


@tool
def sqrt(n: float) -> float:
    """Calculate the square root of a number."""
    return math.sqrt(n)


# ── Agent ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "You are a calculator assistant. Use the provided math tools to solve "
    "problems step by step. Always use tools for calculations — never do "
    "mental math. Show your work, then give the final answer."
)

model = BedrockModel(
    model_id="us.amazon.nova-premier-v1:0",
    region_name="us-east-1",
)

agent = Agent(
    model=model,
    tools=[add, subtract, multiply, divide, power, sqrt],
    system_prompt=SYSTEM_PROMPT,
    name="Smart Calculator",
    description="A calculator that solves math problems step by step using tools.",
)


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        print(f"\n📝 Question: {question}\n")
        result = agent(question)
        print(f"\n✅ Answer: {result}")
    else:
        print("🧮 Strands Smart Calculator (type 'quit' to exit)\n")
        while True:
            question = input("❓ Enter math problem: ").strip()
            if question.lower() in ("quit", "exit", "q"):
                break
            if not question:
                continue
            result = agent(question)
            print(f"\n✅ Answer: {result}\n")
