# 🎫 Jira MCP Server

Connect any AI assistant (GitHub Copilot, Claude Desktop, or any MCP client) to your **Jira Cloud** account.  
Search tickets, create issues, change status, log time — all through natural language.

---

## What can it do? (23 tools)

| # | Tool | What you can ask the AI |
|---|------|------------------------|
| 1 | `server_info` | *"Is my Jira connection working?"* |
| 2 | `myself` | *"Who am I logged in as?"* |
| 3 | `list_projects` | *"What Jira projects do I have access to?"* |
| 4 | `search_issues` | *"Find all open bugs in project ENG"* |
| 5 | `get_issue` | *"Show me the details of ENG-13784"* |
| 6 | `create_issue` | *"Create a Story in ENG: Implement login page"* |
| 7 | `create_subtask` | *"Add a subtask under ENG-123: Write unit tests"* |
| 8 | `update_issue` | *"Change the description of ENG-456"* |
| 9 | `transition_issue` | *"Move ENG-123 to In Progress"* |
| 10 | `get_transitions` | *"What statuses can ENG-123 move to?"* |
| 11 | `add_comment` | *"Comment on ENG-123: Deployed to staging"* |
| 12 | `assign_issue` | *"Assign ENG-123 to ssingh@acs-i.org"* |
| 13 | `add_labels` | *"Add labels ai,poc to ENG-123"* |
| 14 | `remove_labels` | *"Remove the deprecated label from ENG-123"* |
| 15 | `link_issues` | *"ENG-100 blocks ENG-200"* |
| 16 | `log_work` | *"Log 2 hours on ENG-123"* |
| 17 | `add_watcher` | *"Add me as a watcher on ENG-456"* |
| 18 | `get_issue_changelog` | *"Who changed ENG-123 and when?"* |
| 19 | `search_users` | *"Find the user named Singh"* |
| 20 | `delete_issue` | *"Delete ENG-999"* ⚠️ |
| 21 | `my_open_issues` | *"Show me all my open tickets"* |
| 22 | `get_board_sprints` | *"What sprints are active on board 42?"* |
| 23 | `get_sprint_issues` | *"What issues are in sprint 128?"* |

---

## Setup (5 minutes, one time only)

### Prerequisites

- **Python 3.11+** installed ([download here](https://www.python.org/downloads/))
- A **Jira Cloud** account (e.g. `https://your-org.atlassian.net`)

---

### Step 1 — Clone the repo

```bash
git clone https://github.com/Pubs-Digital-Transformation-R-D-Team/at-ai-editor-recommender-l3.git
```

```bash
cd at-ai-editor-recommender-l3/jira-mcp-server
```

---

### Step 2 — Create a virtual environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Mac / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` appear in your terminal prompt.

---

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

---

### Step 4 — Create your Jira API token

1. Open 👉 https://id.atlassian.com/manage-profile/security/api-tokens
2. Log in with the **same email you use for Jira**
3. Click **"Create API token"**
4. Label it `MCP Server` → click **Create**
5. Click **Copy** — save it somewhere, you can't see it again

---

### Step 5 — Find your Jira URL

Open Jira in your browser. Look at the address bar:

```
https://_________.atlassian.net
         ↑ this is your org name
```

Your full Jira URL is something like:
- `https://acsit.atlassian.net`
- `https://mycompany.atlassian.net`

---

### Step 6 — Configure credentials

Copy the template:

**Windows:**
```powershell
copy .env.example .env
```

**Mac / Linux:**
```bash
cp .env.example .env
```

Open `.env` in any editor (Notepad, VS Code, vim — anything) and fill in **3 values**:

```env
JIRA_URL=https://your-org.atlassian.net
JIRA_EMAIL=your-email@company.com
JIRA_API_TOKEN=paste-your-token-from-step-4
```

| Line | What to put | Where to find it |
|------|------------|-----------------|
| `JIRA_URL` | `https://your-org.atlassian.net` | Your browser address bar (Step 5) |
| `JIRA_EMAIL` | `you@company.com` | The email you log in to Jira with |
| `JIRA_API_TOKEN` | `ATATT3xFfGF0...` | The token you copied in Step 4 |

Save the file. **Your credentials are safe** — `.env` is gitignored and will never be pushed.

---

### Step 7 — Test your connection

```bash
python test_connection.py
```

**✅ If it works, you'll see:**
```
1. Testing server_info ...
   URL: https://your-org.atlassian.net
   ✅ Connection OK!

2. Testing myself ...
   Name: Your Name
   Email: you@company.com

3. Testing list_projects ...
   Found 12 project(s)
   - ENG: Engineering (software)
```

**❌ If something is wrong:**

| Error | Fix |
|-------|-----|
| `missing 'http://'` | `JIRA_URL` is empty → open `.env` and add your URL |
| `401 Unauthorized` | Wrong email or expired token → redo Step 4 |
| `0 projects found` | Your account has no project access → ask your Jira admin to add you |

---

### Step 8 — Run the server

**Option A — Web UI (try it visually in the browser):**
```bash
python mcp_server.py
```
Opens http://localhost:7861 — click tabs to search issues, create tickets, etc.

**Option B — Headless (for AI clients like Copilot or Claude):**
```bash
python mcp_server.py --fastmcp
```

---

## Connect to VS Code Copilot

Create or edit `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "jira": {
      "type": "stdio",
      "command": "python",
      "args": ["mcp_server.py", "--fastmcp"],
      "cwd": "/full/path/to/jira-mcp-server",
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "your-email@company.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

> Replace `/full/path/to/jira-mcp-server` with the actual path on your machine.

Then just ask Copilot: *"Show me my open Jira tickets"* — it discovers the tools automatically.

---

## Connect to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["mcp_server.py", "--fastmcp"],
      "cwd": "/full/path/to/jira-mcp-server",
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "your-email@company.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

---

## Quick Reference

### Server modes

| Mode | Command | When to use |
|------|---------|-------------|
| Web UI | `python mcp_server.py` | Testing tools visually at http://localhost:7861 |
| Headless stdio | `python mcp_server.py --fastmcp` | Copilot / Claude Desktop |
| Network SSE | `MCP_TRANSPORT=sse python mcp_server.py --fastmcp` | Remote agents |

### Example JQL queries (for `search_issues`)

```
project = ENG AND status = "In Progress"
assignee = currentUser() AND priority in (High, Highest)
project = ENG AND updated >= -7d ORDER BY updated DESC
labels = "ai" AND project = ENG
sprint in openSprints() AND project = ENG
```

### Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_URL` | Yes | `https://your-org.atlassian.net` |
| `JIRA_EMAIL` | Yes | Your Atlassian email |
| `JIRA_API_TOKEN` | Yes | Token from https://id.atlassian.com/manage-profile/security/api-tokens |
| `MCP_TRANSPORT` | No | `stdio` (default) or `sse` |
| `MCP_PORT` | No | Default `7861` |

---

## Project Structure

```
jira-mcp-server/
├── .env.example               # Template — copy to .env and add your credentials
├── .gitignore                 # Keeps .env and .venv out of git
├── requirements.txt           # pip install -r requirements.txt
├── pyproject.toml             # Project metadata
├── README.md                  # This file
├── jira_client.py             # Jira REST API client (23 functions)
├── mcp_server.py              # MCP server (Gradio + FastMCP modes, 23 tools)
├── claude_desktop_config.json # Example config for Claude Desktop
└── test_connection.py         # Connection smoke test
```
