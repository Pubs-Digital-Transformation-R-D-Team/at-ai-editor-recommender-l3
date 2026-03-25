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

# Create venv and install deps
uv venv .venv --python 3.12
source .venv/bin/activate          # Linux/Mac
# .\.venv\Scripts\Activate.ps1     # Windows

uv pip install httpx "mcp>=1.0.0" "gradio[mcp]>=5.29.0"

# Set your credentials
cp .env.example .env
# Edit .env with your JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN

# Verify connection
python test_connection.py

# Run with Gradio UI (browser + MCP)
python mcp_server.py

# OR run headless for Claude Desktop / Copilot
python mcp_server.py --fastmcp
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
├── .env.example              # Credential template
├── .gitignore                # Keeps .env and .venv out of git
├── uv.toml                   # OneDrive hardlink fix
├── pyproject.toml             # Dependencies
├── README.md
├── jira_client.py            # Jira REST API client (12 functions)
├── mcp_server.py             # MCP server (Gradio + FastMCP modes)
├── claude_desktop_config.json # Example Claude Desktop config
└── test_connection.py        # Connectivity smoke test
```
