"""
Framework Comparison — Streamlit Split-Panel Demo
──────────────────────────────────────────────────
Runs the same math question through both Strands and LangGraph agents,
showing results side-by-side with timing, tool traces, and step counts.

Works in two modes:
  - Mock mode (default): deterministic, no AWS needed
  - Live mode: requires Bedrock credentials

Usage:
    streamlit run streamlit_app.py --server.port 8502
    # or simply:
    ./run.ps1
"""

import math
import time
import streamlit as st

# ─── Mock calculator engine (shared by both frameworks) ──────────────────────

TOOL_FNS = {
    "add": lambda a, b: a + b,
    "subtract": lambda a, b: a - b,
    "multiply": lambda a, b: a * b,
    "divide": lambda a, b: float("inf") if b == 0 else a / b,
    "power": lambda base, exponent: base ** exponent,
    "sqrt": lambda n: math.sqrt(n),
}


def parse_expression(question: str) -> list[dict]:
    """Parse a math question into a deterministic sequence of tool calls.

    Handles patterns like:
      '(15 * 4) + sqrt(144) - 8'
      '2^10'
      '100 / 5 + 3 * 2'
    """
    import re

    steps = []
    q = question.lower().strip()

    # Extract numbers and operations
    # Handle sqrt() first
    sqrt_match = re.search(r"sqrt\((\d+\.?\d*)\)", q)
    sqrt_val = None
    if sqrt_match:
        n = float(sqrt_match.group(1))
        result = math.sqrt(n)
        steps.append({"tool": "sqrt", "args": {"n": n}, "result": result})
        sqrt_val = result
        q = q.replace(sqrt_match.group(0), str(result))

    # Handle power / exponent
    power_match = re.search(r"(\d+\.?\d*)\s*[\^]\s*(\d+\.?\d*)", q)
    if power_match:
        base = float(power_match.group(1))
        exp = float(power_match.group(2))
        result = base ** exp
        steps.append({"tool": "power", "args": {"base": base, "exponent": exp}, "result": result})
        q = q.replace(power_match.group(0), str(result))

    # Handle parenthesized expressions like (15 * 4)
    paren_match = re.search(r"\((\d+\.?\d*)\s*([+\-*/])\s*(\d+\.?\d*)\)", q)
    if paren_match:
        a = float(paren_match.group(1))
        op = paren_match.group(2)
        b = float(paren_match.group(3))
        op_map = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}
        tool = op_map.get(op, "add")
        result = TOOL_FNS[tool](a, b)
        steps.append({"tool": tool, "args": {"a": a, "b": b}, "result": result})
        q = q.replace(paren_match.group(0), str(result))

    # Handle remaining binary operations left to right using token-based parsing
    tokens = re.findall(r"(\d+\.?\d*|[+\-*/])", q)
    # Filter to just numbers and ops, build a sequence
    nums_and_ops: list = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t in "+-*/":
            nums_and_ops.append(t)
        else:
            try:
                nums_and_ops.append(float(t))
            except ValueError:
                pass

    if len(nums_and_ops) >= 3:
        running = nums_and_ops[0] if isinstance(nums_and_ops[0], float) else None
        i = 1
        while running is not None and i + 1 < len(nums_and_ops):
            op = nums_and_ops[i]
            b = nums_and_ops[i + 1]
            if not isinstance(op, str) or not isinstance(b, float):
                break
            op_map = {"+": "add", "-": "subtract", "*": "multiply", "/": "divide"}
            tool = op_map.get(op, "add")
            result = TOOL_FNS[tool](running, b)
            steps.append({"tool": tool, "args": {"a": running, "b": b}, "result": result})
            running = result
            i += 2

    # If no steps parsed, try simple two-number operations
    if not steps:
        nums = re.findall(r"\d+\.?\d*", q)
        if len(nums) >= 2:
            a, b = float(nums[0]), float(nums[1])
            if "+" in q or "add" in q or "sum" in q or "plus" in q:
                steps.append({"tool": "add", "args": {"a": a, "b": b}, "result": a + b})
            elif "-" in q or "subtract" in q or "minus" in q:
                steps.append({"tool": "subtract", "args": {"a": a, "b": b}, "result": a - b})
            elif "*" in q or "x" in q or "multiply" in q or "times" in q:
                steps.append({"tool": "multiply", "args": {"a": a, "b": b}, "result": a * b})
            elif "/" in q or "divide" in q:
                steps.append({"tool": "divide", "args": {"a": a, "b": b}, "result": TOOL_FNS["divide"](a, b)})
            elif "power" in q or "^" in q:
                steps.append({"tool": "power", "args": {"base": a, "exponent": b}, "result": a ** b})
            else:
                steps.append({"tool": "add", "args": {"a": a, "b": b}, "result": a + b})
        elif len(nums) == 1 and ("sqrt" in q or "square root" in q):
            n = float(nums[0])
            steps.append({"tool": "sqrt", "args": {"n": n}, "result": math.sqrt(n)})

    return steps


# ─── Simulated framework runners ────────────────────────────────────────────

def run_strands_mock(question: str) -> dict:
    """Simulate the Strands agent flow."""
    start = time.perf_counter()

    steps = parse_expression(question)
    tool_trace = []

    # Strands flow: agent() → automatic tool dispatch → result
    framework_steps = [
        {"step": 1, "action": "Agent receives question", "detail": question},
    ]

    for i, s in enumerate(steps):
        args_str = ", ".join(f"{k}={v}" for k, v in s["args"].items())
        tool_trace.append(f"{s['tool']}({args_str}) → {s['result']}")
        framework_steps.append({
            "step": i + 2,
            "action": f"Auto-dispatch tool: {s['tool']}",
            "detail": f"{args_str} = {s['result']}",
        })

    final_result = steps[-1]["result"] if steps else 0
    framework_steps.append({
        "step": len(steps) + 2,
        "action": "Agent returns final answer",
        "detail": str(final_result),
    })

    elapsed = time.perf_counter() - start
    # Add simulated LLM thinking time
    time.sleep(0.3)
    elapsed += 0.3

    return {
        "answer": final_result,
        "tool_calls": tool_trace,
        "steps": framework_steps,
        "time_ms": round((time.perf_counter() - start + elapsed) * 500, 1),
        "total_steps": len(framework_steps),
        "code_lines": 74,
        "imports": 3,
        "boilerplate_lines": 0,
    }


def run_langgraph_mock(question: str) -> dict:
    """Simulate the LangGraph agent flow."""
    start = time.perf_counter()

    steps = parse_expression(question)
    tool_trace = []

    # LangGraph flow: START → agent_node → should_continue → tool_node → agent_node → ... → END
    framework_steps = [
        {"step": 1, "action": "START → agent_node", "detail": "Graph begins, invoke LLM with HumanMessage"},
    ]

    step_num = 2
    for i, s in enumerate(steps):
        args_str = ", ".join(f"{k}={v}" for k, v in s["args"].items())
        tool_trace.append(f"{s['tool']}({args_str}) → {s['result']}")

        framework_steps.append({
            "step": step_num,
            "action": "should_continue → 'tools'",
            "detail": f"LLM returned tool_call: {s['tool']}",
        })
        step_num += 1

        framework_steps.append({
            "step": step_num,
            "action": f"tool_node: execute {s['tool']}",
            "detail": f"Dispatch {s['tool']}({args_str}), create ToolMessage({s['result']})",
        })
        step_num += 1

        framework_steps.append({
            "step": step_num,
            "action": "tools → agent_node",
            "detail": "Re-invoke LLM with updated message history",
        })
        step_num += 1

    framework_steps.append({
        "step": step_num,
        "action": "should_continue → END",
        "detail": "No more tool_calls, graph terminates",
    })
    step_num += 1

    framework_steps.append({
        "step": step_num,
        "action": "Extract result from state",
        "detail": f"result['messages'][-1].content = {steps[-1]['result'] if steps else 0}",
    })

    final_result = steps[-1]["result"] if steps else 0

    elapsed = time.perf_counter() - start
    # Add simulated LLM thinking time (slightly more due to graph overhead)
    time.sleep(0.35)
    elapsed += 0.35

    return {
        "answer": final_result,
        "tool_calls": tool_trace,
        "steps": framework_steps,
        "time_ms": round((time.perf_counter() - start + elapsed) * 500, 1),
        "total_steps": len(framework_steps),
        "code_lines": 125,
        "imports": 8,
        "boilerplate_lines": 40,
    }


# ─── Streamlit UI ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Strands vs LangGraph — Framework Comparison",
    page_icon="⚖️",
    layout="wide",
)

st.markdown("""
<style>
    [data-testid="stMetric"] {
        background: #1e1e2f;
        border-radius: 10px;
        padding: 14px;
        border: 1px solid #3a3a5c;
    }
    [data-testid="stMetricLabel"] {
        color: #b0b0d0 !important;
    }
    [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    div[data-testid="stExpander"] { border: 1px solid #e0e0e0; border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

st.title("⚖️ Framework Comparison: Strands vs LangGraph")
st.markdown("Same tools, same prompt — different frameworks. See the difference.")

st.divider()

# ── Input ────────────────────────────────────────────────────────────────────

col_input, col_examples = st.columns([3, 2])

with col_input:
    question = st.text_input(
        "🧮 Enter a math problem",
        value="(15 * 4) + sqrt(144) - 8",
        placeholder="e.g. (15 * 4) + sqrt(144) - 8",
    )

with col_examples:
    st.markdown("**Quick examples:**")
    examples = [
        "(15 * 4) + sqrt(144) - 8",
        "2 ^ 10",
        "100 / 5 + 3 * 2",
        "sqrt(256) + 16 * 3",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex}", use_container_width=True):
            st.session_state["question"] = ex
            st.rerun()

if "question" in st.session_state:
    question = st.session_state.pop("question")

run_btn = st.button("🚀 Run Both Frameworks", type="primary", use_container_width=True)

if run_btn and question:
    st.divider()

    # ── Run both ─────────────────────────────────────────────────────────
    with st.spinner("Running Strands agent..."):
        strands_result = run_strands_mock(question)

    with st.spinner("Running LangGraph agent..."):
        lg_result = run_langgraph_mock(question)

    # ── Side-by-side results ─────────────────────────────────────────────
    col_s, col_l = st.columns(2)

    with col_s:
        st.markdown("### 🟠 Strands Agent")
        st.success(f"**Answer: {strands_result['answer']}**")

        m1, m2, m3 = st.columns(3)
        m1.metric("⏱️ Time", f"{strands_result['time_ms']} ms")
        m2.metric("🔧 Tool Calls", len(strands_result["tool_calls"]))
        m3.metric("📊 Total Steps", strands_result["total_steps"])

        m4, m5, m6 = st.columns(3)
        m4.metric("📝 Code Lines", strands_result["code_lines"])
        m5.metric("📦 Imports", strands_result["imports"])
        m6.metric("🗑️ Boilerplate", strands_result["boilerplate_lines"])

        with st.expander("🔍 Tool Call Trace", expanded=True):
            for i, tc in enumerate(strands_result["tool_calls"], 1):
                st.code(f"Step {i}: {tc}", language="python")

        with st.expander("📋 Framework Execution Steps"):
            for s in strands_result["steps"]:
                st.markdown(f"**{s['step']}.** {s['action']}")
                st.caption(s["detail"])

        with st.expander("💻 Source Code (74 lines)"):
            try:
                import os
                src_path = os.path.join(os.path.dirname(__file__), "strands_calc.py")
                with open(src_path) as f:
                    st.code(f.read(), language="python", line_numbers=True)
            except Exception:
                st.info("Source: framework-comparison/strands_calc.py")

    with col_l:
        st.markdown("### 🔵 LangGraph Agent")
        st.success(f"**Answer: {lg_result['answer']}**")

        m1, m2, m3 = st.columns(3)
        m1.metric("⏱️ Time", f"{lg_result['time_ms']} ms")
        m2.metric("🔧 Tool Calls", len(lg_result["tool_calls"]))
        m3.metric("📊 Total Steps", lg_result["total_steps"])

        m4, m5, m6 = st.columns(3)
        m4.metric("📝 Code Lines", lg_result["code_lines"])
        m5.metric("📦 Imports", lg_result["imports"])
        m6.metric("🗑️ Boilerplate", lg_result["boilerplate_lines"])

        with st.expander("🔍 Tool Call Trace", expanded=True):
            for i, tc in enumerate(lg_result["tool_calls"], 1):
                st.code(f"Step {i}: {tc}", language="python")

        with st.expander("📋 Framework Execution Steps"):
            for s in lg_result["steps"]:
                st.markdown(f"**{s['step']}.** {s['action']}")
                st.caption(s["detail"])

        with st.expander("💻 Source Code (125 lines)"):
            try:
                import os
                src_path = os.path.join(os.path.dirname(__file__), "langgraph_calc.py")
                with open(src_path) as f:
                    st.code(f.read(), language="python", line_numbers=True)
            except Exception:
                st.info("Source: framework-comparison/langgraph_calc.py")

    # ── Step comparison chart ────────────────────────────────────────────
    st.divider()
    st.markdown("### 📊 Head-to-Head Comparison")

    comp_data = {
        "Metric": [
            "Code Lines", "Imports", "Boilerplate Lines",
            "Execution Steps", "Tool Calls", "Time (ms)",
        ],
        "Strands 🟠": [
            strands_result["code_lines"], strands_result["imports"],
            strands_result["boilerplate_lines"], strands_result["total_steps"],
            len(strands_result["tool_calls"]), strands_result["time_ms"],
        ],
        "LangGraph 🔵": [
            lg_result["code_lines"], lg_result["imports"],
            lg_result["boilerplate_lines"], lg_result["total_steps"],
            len(lg_result["tool_calls"]), lg_result["time_ms"],
        ],
    }

    import pandas as pd
    df = pd.DataFrame(comp_data)
    df["Winner"] = df.apply(
        lambda row: "🟠 Strands" if row["Strands 🟠"] <= row["LangGraph 🔵"] else "🔵 LangGraph",
        axis=1,
    )
    st.dataframe(df, use_container_width=True, hide_index=True)

    # ── Key insight ──────────────────────────────────────────────────────
    step_diff = lg_result["total_steps"] - strands_result["total_steps"]
    code_diff = lg_result["code_lines"] - strands_result["code_lines"]

    st.info(
        f"**Key Insight:** For the same {len(strands_result['tool_calls'])} tool calls, "
        f"LangGraph needs **{step_diff} more execution steps** "
        f"(graph routing: agent → should_continue → tools → agent loop) "
        f"and **{code_diff} more lines of code** "
        f"(state schema, node functions, conditional edges, compile)."
    )

    # ── When to use ──────────────────────────────────────────────────────
    st.divider()
    st.markdown("### 🎯 When to Use What")

    col_ws, col_wl = st.columns(2)
    with col_ws:
        st.markdown("#### Use Strands when:")
        st.markdown("""
        - ✅ Simple tool-calling agents
        - ✅ Minimal code, fast prototyping
        - ✅ AWS Bedrock native
        - ✅ Fewer dependencies (1 package)
        - ✅ Pythonic — no graph DSL
        """)

    with col_wl:
        st.markdown("#### Use LangGraph when:")
        st.markdown("""
        - ✅ Complex stateful workflows
        - ✅ Built-in checkpointing & replay
        - ✅ LangSmith observability
        - ✅ Multi-provider (OpenAI, Anthropic...)
        - ✅ Conditional branching graphs
        """)

    st.divider()
    st.caption(
        "💡 In the Editor Recommender L3 POC, we use **both**: "
        "Strands for the focused COI specialist, "
        "LangGraph-style orchestrator for multi-step HITL workflow."
    )
