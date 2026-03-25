# 🎫 Jira MCP Server

General-purpose **Model Context Protocol** server for **Jira Cloud**.  
Works with Claude Desktop, VS Code Copilot, or any MCP-compatible AI agent.

---

## Tools Exposed

| Tool | Description |
|------|-------------|
| `server_info` | Verify Jira connectivity and version |
| `myself` | Get current authenticated user info |
| `list_projects` | List all Jira projects you have access to |
| `search_issues` | Search using JQL (Jira Query Language) |
| `get_issue` | Get full details of an issue (description, comments, status) |
| `create_issue` | Create a new issue (Task, Bug, Story, Epic) |
| `update_issue` | Update fields on an existing issue |
| `transition_issue` | Change status (To Do → In Progress → Done) |
| `add_comment` | Add a comment to an issue |
| `assign_issue` | Assign an issue to a user by email |
| `my_open_issues` | Get all open issues assigned to you |
| `get_board_sprints` | Get active/future sprints for a board |

---

## Quick Start

```bash
cd jira-mcp-server

# 1. Create a virtual environment
python -m venv .venv
source .venv/bin/activate          # Linux/Mac
# .\.venv\Scripts\Activate.ps1     # Windows (PowerShell)

# 2. Install dependencies (pick one)
pip install -r requirements.txt    # standard pip
# uv pip install -r requirements.txt  # or use uv (faster)

# 3. Configure credentials
cp .env.example .env               # Linux/Mac
# copy .env.example .env            # Windows
# Then edit .env with your values:
#   JIRA_URL=https://your-org.atlassian.net
#   JIRA_EMAIL=you@company.com
#   JIRA_API_TOKEN=your-token-from-atlassian

# 4. Verify connection
python test_connection.py

# 5. Run the MCP server
python mcp_server.py               # Gradio UI + MCP (http://localhost:7861)
python mcp_server.py --fastmcp     # Headless — for Claude Desktop / VS Code Copilot
```

### Get your API token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **"Create API token"**
3. Copy the token into your `.env` file
```

---

## Modes

### Mode 1: Gradio (Web UI + MCP)
```bash
python mcp_server.py
# Opens http://localhost:7861 with a web UI
# MCP endpoint at http://localhost:7861/gradio_api/mcp/sse
```

### Mode 2: FastMCP (stdio — for Claude Desktop / VS Code Copilot)
```bash
python mcp_server.py --fastmcp
```

### Mode 3: FastMCP (SSE — for remote agents)
```bash
MCP_TRANSPORT=sse python mcp_server.py --fastmcp
# MCP SSE endpoint at http://localhost:7861/sse
```

---

## IDE / Client Setup

### Claude Desktop

Add to `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "jira": {
      "command": "python",
      "args": ["mcp_server.py", "--fastmcp"],
      "cwd": "/path/to/jira-mcp-server",
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "you@company.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

### VS Code Copilot

Add to `.vscode/mcp.json`:
```json
{
  "servers": {
    "jira": {
      "type": "stdio",
      "command": "/path/to/jira-mcp-server/.venv/Scripts/python.exe",
      "args": ["mcp_server.py", "--fastmcp"],
      "cwd": "/path/to/jira-mcp-server",
      "env": {
        "JIRA_URL": "https://your-org.atlassian.net",
        "JIRA_EMAIL": "you@company.com",
        "JIRA_API_TOKEN": "your-token"
      }
    }
  }
}
```

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
├── requirements.txt           # pip install -r requirements.txt
├── pyproject.toml             # Project metadata + dependencies
├── README.md
├── jira_client.py            # Jira REST API client (12 functions)
├── mcp_server.py             # MCP server (Gradio + FastMCP modes)
├── claude_desktop_config.json # Example Claude Desktop config
└── test_connection.py        # Connectivity smoke test
```


