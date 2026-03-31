# Framework Comparison: Strands vs LangGraph

Same app, same tools, same prompt — different frameworks.  
Both use **AWS Bedrock Nova Premier** as the LLM.

---

## The App

A **Smart Calculator** agent with 6 math tools:
`add`, `subtract`, `multiply`, `divide`, `power`, `sqrt`

The agent solves multi-step math problems by calling tools step by step.

---

## Code Size

| | Strands | LangGraph |
|---|---------|-----------|
| **Total lines** | 74 | 125 |
| **Tool definitions** | 30 | 35 |
| **Agent setup** | 12 | 50+ |
| **Boilerplate** | 0 | ~40 |
| **Imports** | 3 | 8 |
| **Files** | 1 | 1 |

---

## Side-by-Side

### Tool Definition

**Strands** — native Python, return any type:
```python
@tool
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b
```

**LangGraph** — must return strings, different decorator:
```python
@lc_tool
def add(a: float, b: float) -> str:
    """Add two numbers."""
    return str(a + b)
```

### Agent Creation

**Strands** — 6 lines, done:
```python
agent = Agent(
    model=BedrockModel(model_id="us.amazon.nova-premier-v1:0"),
    tools=[add, subtract, multiply, divide, power, sqrt],
    system_prompt=SYSTEM_PROMPT,
)
result = agent("What is 15 * 4 + 12?")
```

**LangGraph** — state schema, nodes, edges, conditional routing, compile:
```python
# 1. Define state schema
class CalcState(TypedDict):
    messages: Annotated[list, add_messages]

# 2. Bind tools to LLM
llm_with_tools = llm.bind_tools(TOOLS)

# 3. Define agent node
def agent_node(state):
    return {"messages": [llm_with_tools.invoke(state["messages"])]}

# 4. Define tool execution node
def tool_node(state):
    # manually dispatch tool calls...

# 5. Define routing logic
def should_continue(state):
    if last_message.tool_calls:
        return "tools"
    return END

# 6. Build graph
graph = StateGraph(CalcState)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)
graph.add_edge(START, "agent")
graph.add_conditional_edges("agent", should_continue)
graph.add_edge("tools", "agent")

# 7. Compile
calculator = graph.compile()

# 8. Invoke
result = calculator.invoke({"messages": [HumanMessage(content="What is 15 * 4 + 12?")]})
```

---

## Comparison Matrix

| Feature | Strands | LangGraph |
|---------|---------|-----------|
| **Learning curve** | ⭐ Low — feels like plain Python | ⭐⭐⭐ Higher — graph concepts, state management |
| **Tool calling** | ⭐ Built-in, automatic dispatch | ⭐⭐ Manual dispatch via `ToolMessage` |
| **Boilerplate** | ⭐ Minimal — `Agent()` + `@tool` | ⭐⭐⭐ State schema, nodes, edges, routing |
| **Multi-step reasoning** | ⭐ Automatic tool loop | ⭐⭐ Explicit graph cycle (agent → tools → agent) |
| **Bedrock integration** | ⭐ Native `BedrockModel` | ⭐⭐ Via `langchain-aws` wrapper |
| **Complex workflows** | ⭐⭐ Agent-to-agent via A2A | ⭐ Graph nodes + subgraphs + checkpoints |
| **Human-in-the-loop** | ⭐⭐ Via A2A protocol | ⭐ Built-in interrupt/resume |
| **Streaming** | ⭐ Built-in | ⭐ Built-in via `.astream()` |
| **State persistence** | ⭐⭐ Manual / external | ⭐ Built-in checkpointing |
| **Observability** | ⭐⭐ CloudWatch / custom | ⭐ LangSmith integration |
| **Community / ecosystem** | ⭐⭐ Growing (AWS-backed) | ⭐ Large (LangChain ecosystem) |
| **Vendor lock-in** | ⭐⭐ AWS-focused | ⭐ Multi-provider |
| **Dependencies** | ⭐ 1 package (`strands-agents`) | ⭐⭐⭐ 3+ packages (`langgraph`, `langchain-aws`, `langchain-core`) |

---

## When to Use What

### Use **Strands** when:
- You want **minimal code** and fast prototyping
- Your agents use **AWS Bedrock** (native integration)
- You need **simple tool-calling agents** without complex orchestration
- You prefer **Pythonic** code over graph DSLs
- You want **fewer dependencies** and a smaller attack surface

### Use **LangGraph** when:
- You need **complex, stateful workflows** (branching, loops, checkpoints)
- You need **built-in persistence** and replay of agent state
- You want **LangSmith** observability out of the box
- You need **multi-provider LLM support** (OpenAI, Anthropic, Google, etc.)
- Your workflow has **conditional branching** that maps naturally to a graph

---

## Run It

```bash
# Install dependencies
pip install -r requirements.txt

# Strands version
python strands_calc.py "What is (15 * 4) + sqrt(144) - 8?"

# LangGraph version
python langgraph_calc.py "What is (15 * 4) + sqrt(144) - 8?"

# Interactive mode (either)
python strands_calc.py
python langgraph_calc.py
```

> Both require AWS Bedrock credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`).

---

## Bottom Line

| | Strands | LangGraph |
|---|---------|-----------|
| **Same app, same result** | ✅ 74 lines | ✅ 125 lines |
| **Time to build** | ~5 min | ~15 min |
| **Cognitive load** | Low | Medium-High |

**Strands wins on simplicity.** For straightforward tool-calling agents, it's less code, fewer concepts, and faster to ship.

**LangGraph wins on power.** When you need stateful multi-step workflows with branching, checkpointing, and replay, the graph abstraction pays for itself.

For the **Editor Recommender L3 POC**, we use **both**: Strands for the focused COI specialist agent, and the LangGraph-style orchestrator for the complex multi-step workflow with HITL.
