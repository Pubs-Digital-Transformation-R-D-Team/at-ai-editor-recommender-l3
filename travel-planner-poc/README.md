# 🌍 Travel Planner Memory POC

**Strands Agent + Postgres** — L2 (Session) + L3 (Long-term) memory.

## Architecture

```mermaid
graph TB
    subgraph UI["Streamlit UI (:8502)"]
        T1["🗺️ Plan a Trip<br/><i>step-by-step guided</i>"]
        T2["🤖 Agent Chat<br/><i>Strands LLM</i>"]
        T3["📜 Past Trips"]
        T4["🧠 Memory Browser"]
        T5["💥 Crash Recovery"]
        T6["📊 Preferences"]
    end

    subgraph AGENT["Strands Agent (agent.py)"]
        LLM["Bedrock Nova Premier<br/>+ system prompt"]
    end

    subgraph TOOLS["@tool functions (tools.py)"]
        direction LR
        MR["L3 READ<br/>get_preferences()<br/>search_past_trips()"]
        MW["L3 WRITE<br/>save_trip_to_memory()<br/>save_user_preference()"]
        PT["Planning<br/>search_hotels()<br/>search_activities()<br/>get_weather()"]
    end

    subgraph MEM["memory.py"]
        SQL["SQL queries<br/>SELECT / INSERT / UPSERT"]
    end

    subgraph PG["Postgres (RDS)"]
        direction LR
        SC["session_checkpoints<br/><i>L2 — crash recovery</i>"]
        TH["trip_history<br/><i>L3 — past trips</i>"]
        TP["travel_preferences<br/><i>L3 — taste profile</i>"]
    end

    MOCK["mock_data.py<br/><i>hotels, activities, weather</i>"]

    T2 -->|user message| LLM
    LLM -->|auto-calls| MR
    LLM -->|auto-calls| MW
    LLM -->|auto-calls| PT
    T1 -->|direct read/write| SQL
    MR --> SQL
    MW --> SQL
    PT --> MOCK
    SQL --> SC
    SQL --> TH
    SQL --> TP

    style UI fill:#1a1a2e,color:#fff
    style AGENT fill:#2d1b4e,color:#fff
    style TOOLS fill:#1b3a4e,color:#fff
    style PG fill:#1b4e2d,color:#fff
```

## Agent Flow — How Memory Makes Decisions Better

```mermaid
sequenceDiagram
    actor User
    participant Agent as Strands Agent<br/>(Bedrock Nova)
    participant Tools as @tool functions
    participant PG as Postgres

    Note over User,PG: FIRST TRIP (no memory)
    User->>Agent: Plan a trip to Tokyo
    Agent->>Tools: get_preferences()
    Tools->>PG: SELECT FROM travel_preferences
    PG-->>Tools: EMPTY ❌
    Agent->>Tools: search_past_trips("Tokyo")
    Tools->>PG: SELECT FROM trip_history
    PG-->>Tools: EMPTY ❌
    Agent->>Tools: search_hotels("Tokyo") — no filters
    Agent->>Tools: search_activities("Tokyo") — no filters
    Agent-->>User: Generic plan (all hotels, all activities)

    User->>Agent: Loved it! Rate 4/5. Tsukiji amazing, Shibuya too crowded.
    Agent->>Tools: save_trip_to_memory(Tokyo, 4/5, ...)
    Tools->>PG: INSERT INTO trip_history ✅
    Agent->>Tools: save_user_preference(accom_style=boutique)
    Agent->>Tools: save_user_preference(avoid_crowds=true)
    Tools->>PG: UPSERT INTO travel_preferences ✅

    Note over User,PG: NEXT TRIP (memory kicks in)
    User->>Agent: Plan a trip to Osaka
    Agent->>Tools: get_preferences()
    Tools->>PG: SELECT FROM travel_preferences
    PG-->>Tools: boutique(85%), $150(70%), food+cultural(85%), avoid_crowds(75%)
    Agent->>Tools: search_past_trips("Japan")
    Tools->>PG: SELECT FROM trip_history WHERE ILIKE 'Japan'
    PG-->>Tools: Tokyo trip — loved Tsukiji, hated crowds
    Agent->>Tools: search_hotels("Osaka", type=boutique, max=150)
    Agent->>Tools: search_activities("Osaka", type=food, crowd=moderate)
    Agent-->>User: Personalised plan ✅<br/>Boutique hotel, Kuromon Market,<br/>skips crowded Dotonbori
```

## L2 Crash Recovery Flow

```mermaid
sequenceDiagram
    actor User
    participant App as Streamlit
    participant PG as Postgres

    User->>App: Pick Barcelona, choose hotel, pick activities
    App->>PG: Checkpoint 1 — destination ✅
    App->>PG: Checkpoint 2 — hotel chosen ✅
    App->>PG: Checkpoint 3 — activities chosen ✅

    Note over User,PG: 💥 CRASH (pod restart / browser close)

    User->>App: Reopens app
    App->>PG: Load latest checkpoint for session
    PG-->>App: Step 3 state (destination + hotel + activities)
    App-->>User: "Welcome back! You were planning Barcelona.<br/>Hotel Neri selected. Resume from Day 2?"
```

## Quick Start

```powershell
pip install strands-agents strands-agents-bedrock psycopg2-binary streamlit python-dotenv
.\start.ps1 --seed
```

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Strands Agent — Bedrock Nova + system prompt |
| `tools.py` | 7 `@tool` functions (memory read/write + hotels/activities/weather) |
| `memory.py` | L2 checkpoint + L3 trip/preference read/write |
| `mock_data.py` | Mock data for 8 cities |
| `db.py` | Postgres connection, DDL, `seed_demo_data()` |
| `streamlit_app.py` | 6-tab UI |

## UI Tabs

| Tab | What |
|-----|------|
| 🗺️ Plan a Trip | Step-by-step guided planner (side-by-side WITH/WITHOUT memory) |
| 🤖 Agent Chat | **Strands LLM** — chat with the agent, it calls tools autonomously |
| 📜 Past Trips | Browse L3 trip_history |
| 🧠 Memory Browser | Raw Postgres tables |
| 💥 Crash Recovery | L2 session checkpoint demo |
| 📊 Preferences | L3 preference dashboard |
