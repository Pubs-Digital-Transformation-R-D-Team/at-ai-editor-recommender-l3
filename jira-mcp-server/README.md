# 🎫 Jira MCP Server

General-purpose **Model Context Protocol** server for **Jira Cloud**.  
Works with Claude Desktop, VS Code Copilot, or any MCP-compatible AI agent.

---

## Tools Exposed (22 tools)

| # | Tool | Description |
|---|------|-------------|
| 1 | `server_info` | Verify Jira connectivity and version |
| 2 | `myself` | Get current authenticated user info |
| 3 | `list_projects` | List all Jira projects you have access to |
| 4 | `search_issues` | Search using JQL (Jira Query Language) |
| 5 | `get_issue` | Get full details of an issue (description, comments, status) |
| 6 | `create_issue` | Create a new issue (Task, Bug, Story, Epic) |
| 7 | `create_subtask` | Create a subtask under an existing issue |
| 8 | `update_issue` | Update fields on an existing issue |
| 9 | `transition_issue` | Change status (To Do → In Progress → Done) |
| 10 | `get_transitions` | List available status transitions for an issue |
| 11 | `add_comment` | Add a comment to an issue |
| 12 | `assign_issue` | Assign an issue to a user by email |
| 13 | `add_labels` | Add labels to an issue (keeps existing ones) |
| 14 | `remove_labels` | Remove specific labels from an issue |
| 15 | `link_issues` | Link two issues (Relates, Blocks, Duplicate, etc.) |
| 16 | `log_work` | Log time spent on an issue (e.g. "2h", "1d 4h") |
| 17 | `add_watcher` | Add a watcher to an issue for notifications |
| 18 | `get_issue_changelog` | Get change history — who changed what and when |
| 19 | `search_users` | Search for Jira users by name or email |
| 20 | `delete_issue` | Delete an issue (with optional subtask deletion) |
| 21 | `my_open_issues` | Get all open issues assigned to you |
| 22 | `get_board_sprints` | Get active/future sprints for a board |
| 23 | `get_sprint_issues` | Get all issues in a specific sprint |

---

## Setup — Step by Step

### Step 1: Clone the repo

```bash
git clone https://github.com/Pubs-Digital-Transformation-R-D-Team/at-ai-editor-recommender-l3.git
cd at-ai-editor-recommender-l3/jira-mcp-server
```

### Step 2: Create a virtual environment

**Mac / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Create a Jira API token

1. Open your browser and go to:  
   👉 https://id.atlassian.com/manage-profile/security/api-tokens

2. Log in with your **Atlassian account** (the same email you use for Jira)

3. Click **"Create API token"**

4. Enter a label (e.g. `MCP Server`) and click **Create**

5. **Copy the token** — you won't be able to see it again

### Step 5: Find your Jira URL

Your Jira URL is the address you see when you open Jira in your browser. It looks like:

```
https://your-org.atlassian.net
```

For example:
- `https://acsit.atlassian.net`
- `https://mycompany.atlassian.net`

### Step 6: Configure your credentials

1. Copy the example env file:

   **Mac / Linux:**
   ```bash
   cp .env.example .env
   ```

   **Windows:**
   ```powershell
   copy .env.example .env
   ```

2. Open `.env` in any text editor and fill in your values:

   ```env
   JIRA_URL=https://your-org.atlassian.net
   JIRA_EMAIL=your-email@company.com
   JIRA_API_TOKEN=paste-your-api-token-here
   ```

   | Field | Where to find it | Example |
   |-------|-----------------|---------|
   | `JIRA_URL` | Your browser address bar when on Jira | `https://acsit.atlassian.net` |
   | `JIRA_EMAIL` | The email you log in to Jira with | `ssingh@acs-i.org` |
   | `JIRA_API_TOKEN` | Copied from Step 4 above | `ATATT3xFfGF0...` |

3. **Save the file.** The `.env` file is gitignored — your credentials will never be committed.

### Step 7: Verify your connection

```bash
python test_connection.py
```

You should see:
```
==================================================
JIRA MCP SERVER — CONNECTION TEST
==================================================

1. Testing server_info ...
   URL: https://your-org.atlassian.net
   Version: 1001.0.0-SNAPSHOT
   Deployment: Cloud
   ✅ Connection OK!

2. Testing myself ...
   Name: Your Name
   Email: your-email@company.com

3. Testing list_projects ...
   Found 12 project(s)
   - ENG: Engineering (software)
   - ...
```

If you see `✅ Connection OK!` — you're all set.

**Troubleshooting:**
- `❌ missing 'http://'` → Your `JIRA_URL` is empty. Check `.env` file.
- `401 Unauthorized` → Wrong email or token. Regenerate the token in Step 4.
- `0 projects found` → Your Jira account doesn't have project access. Ask your Jira admin.

### Step 8: Run the MCP server

**Option A — Gradio Web UI (visual, try tools in the browser):**
```bash
python mcp_server.py
```
Opens http://localhost:7861 with tabs for Search, Create Issue, Add Comment, etc.

**Option B — Headless for AI clients (Claude Desktop / VS Code Copilot):**
```bash
python mcp_server.py --fastmcp
```

---

## Connect to your IDE

### VS Code Copilot

Add this to your `.vscode/mcp.json` (create the file if it doesn't exist):

```json
{
  "servers": {
    "jira": {
      "type": "stdio",
      "command": "python",
      "args": ["mcp_server.py", "--fastmcp"],
      "cwd": "/path/to/jira-mcp-server",
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "your-email@company.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

> Replace `/path/to/jira-mcp-server` with the actual folder path on your machine.

### Claude Desktop

Add this to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["mcp_server.py", "--fastmcp"],
      "cwd": "/path/to/jira-mcp-server",
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "your-email@company.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

Once configured, just ask the AI:
- *"Show me my Jira tickets"*
- *"Create a bug in project ENG for the login crash"*
- *"Move ENG-123 to Done"*

---

## Server Modes

| Mode | Command | Use case |
|------|---------|----------|
| Gradio UI | `python mcp_server.py` | Try tools visually at http://localhost:7861 |
| FastMCP stdio | `python mcp_server.py --fastmcp` | Claude Desktop / VS Code Copilot |
| FastMCP SSE | `MCP_TRANSPORT=sse python mcp_server.py --fastmcp` | Remote agents over network |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `JIRA_URL` | Yes | Your Jira Cloud URL (e.g. `https://your-org.atlassian.net`) |
| `JIRA_EMAIL` | Yes | Your Atlassian account email |
| `JIRA_API_TOKEN` | Yes | API token from https://id.atlassian.com/manage-profile/security/api-tokens |
| `MCP_TRANSPORT` | No | `stdio` (default) or `sse` for network mode |
| `MCP_PORT` | No | Port for Gradio/SSE mode (default: `7861`) |

---

## Example JQL Queries

Once connected, you can search Jira using JQL:

```
# All open bugs in a project
project = ENG AND issuetype = Bug AND statusCategory != Done

# My high-priority tasks
assignee = currentUser() AND priority in (High, Highest)

# Recently updated issues
project = ENG AND updated >= -7d ORDER BY updated DESC

# Issues with a specific label
labels = "ai" AND project = ENG

# Sprint-related
sprint in openSprints() AND project = ENG
```

---

## Project Structure

```
jira-mcp-server/
├── .env.example              # Credential template — copy to .env
├── .gitignore                # Keeps .env and .venv out of git
├── requirements.txt          # pip install -r requirements.txt
├── pyproject.toml            # Project metadata + dependencies
├── README.md                 # This file
├── jira_client.py            # Jira REST API client (12 functions)
├── mcp_server.py             # MCP server (Gradio + FastMCP modes)
├── claude_desktop_config.json # Example Claude Desktop config
└── test_connection.py        # Connectivity smoke test
```

