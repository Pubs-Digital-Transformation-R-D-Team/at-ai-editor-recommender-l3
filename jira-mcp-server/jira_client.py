"""
Jira REST API Client
─────────────────────
Thin wrapper around Jira Cloud REST API v3.
All functions return plain dicts/strings suitable for MCP tool responses.
"""

import json
import os
from base64 import b64encode
from pathlib import Path

import httpx

# Auto-load .env if present (so credentials work without manually setting env vars)
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

JIRA_URL = os.getenv("JIRA_URL", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

# Validate — give clear setup instructions if credentials are missing
_missing = [v for v in ["JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"] if not os.getenv(v)]
if _missing:
    import warnings
    warnings.warn(
        f"\n\n  Jira MCP Server — missing configuration: {', '.join(_missing)}\n"
        f"  Setup:\n"
        f"    1. Copy .env.example to .env\n"
        f"    2. Fill in your JIRA_URL, JIRA_EMAIL, and JIRA_API_TOKEN\n"
        f"    3. Get an API token at: https://id.atlassian.com/manage-profile/security/api-tokens\n",
        stacklevel=2,
    )

_BASE = f"{JIRA_URL}/rest/api/3"


def _headers() -> dict:
    cred = b64encode(f"{JIRA_EMAIL}:{JIRA_API_TOKEN}".encode()).decode()
    return {
        "Authorization": f"Basic {cred}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(path: str, params: dict | None = None) -> dict:
    r = httpx.get(f"{_BASE}{path}", headers=_headers(), params=params, timeout=30.0)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict) -> dict:
    r = httpx.post(f"{_BASE}{path}", headers=_headers(), json=body, timeout=30.0)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> int:
    r = httpx.put(f"{_BASE}{path}", headers=_headers(), json=body, timeout=30.0)
    r.raise_for_status()
    return r.status_code


# ─── Server info / connectivity check ────────────────────────────────────────

def server_info() -> str:
    """Get Jira server info — confirms connectivity and authentication."""
    data = _get("/serverInfo")
    return json.dumps({
        "url": data.get("baseUrl", ""),
        "version": data.get("version", ""),
        "deployment": data.get("deploymentType", ""),
        "build": data.get("buildNumber", ""),
    }, indent=2)


def myself() -> str:
    """Get current authenticated user info."""
    try:
        data = _get("/myself")
        return json.dumps({
            "name": data.get("displayName", ""),
            "email": data.get("emailAddress", ""),
            "active": data.get("active", False),
            "account_id": data.get("accountId", ""),
        }, indent=2)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return json.dumps({
                "error": "Token lacks permission for /myself. Auth works for other endpoints.",
                "hint": "This is normal for scoped API tokens. Use server_info to verify connectivity.",
            }, indent=2)
        raise


# ─── Projects ────────────────────────────────────────────────────────────────

def list_projects() -> str:
    """List all Jira projects you have access to."""
    # Try /project/search first (paginated, works with scoped tokens)
    try:
        raw = _get("/project/search", params={"maxResults": 50})
        items = raw.get("values", [])
    except httpx.HTTPStatusError:
        # Fallback to /project (legacy, returns a flat list)
        raw = _get("/project", params={"maxResults": 50})
        items = raw if isinstance(raw, list) else raw.get("values", [])

    projects = []
    for p in items:
        projects.append({
            "key": p.get("key", ""),
            "name": p.get("name", ""),
            "type": p.get("projectTypeKey", ""),
            "lead": p.get("lead", {}).get("displayName", "") if isinstance(p.get("lead"), dict) else "",
        })
    return json.dumps(projects, indent=2)


# ─── Search / JQL ────────────────────────────────────────────────────────────

def search_issues(jql: str, max_results: int = 20) -> str:
    """
    Search Jira issues using JQL (Jira Query Language).

    Examples:
      - project = ER AND status = "In Progress"
      - assignee = currentUser() ORDER BY priority DESC
      - text ~ "editor recommender" AND created >= -7d
    """
    # Jira Cloud deprecated /search in 2025 — use /search/jql
    try:
        data = _get("/search/jql", params={
            "jql": jql,
            "maxResults": max_results,
            "fields": "summary,status,priority,assignee,created,updated,issuetype,labels",
        })
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 410:
            # Fallback to legacy endpoint for on-prem / older Jira
            data = _get("/search", params={
                "jql": jql,
                "maxResults": max_results,
                "fields": "summary,status,priority,assignee,created,updated,issuetype,labels",
            })
        elif e.response.status_code == 400:
            # Jira Cloud rejects unbounded queries — return the error with hints
            try:
                err_body = e.response.json()
                err_msgs = err_body.get("errorMessages", [])
            except Exception:
                err_msgs = [e.response.text[:300]]
            return json.dumps({
                "error": err_msgs[0] if err_msgs else "Bad JQL query",
                "jql_sent": jql,
                "hint": "Jira Cloud requires a bounded query. Add 'project = KEY' to your JQL.",
                "examples": [
                    "project = ER ORDER BY updated DESC",
                    "project = ER AND status = 'In Progress'",
                    "project = ER AND assignee = currentUser()",
                ],
                "total": 0,
                "showing": 0,
                "issues": [],
            }, indent=2)
        else:
            raise
    issues = []
    for i in data.get("issues", []):
        f = i["fields"]
        issues.append({
            "key": i["key"],
            "summary": f.get("summary", ""),
            "status": f.get("status", {}).get("name", ""),
            "priority": f.get("priority", {}).get("name", ""),
            "type": f.get("issuetype", {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
            "labels": f.get("labels", []),
            "created": f.get("created", ""),
            "updated": f.get("updated", ""),
        })
    return json.dumps({
        "total": data.get("total", 0),
        "showing": len(issues),
        "issues": issues,
    }, indent=2)


# ─── Get single issue ────────────────────────────────────────────────────────

def get_issue(issue_key: str) -> str:
    """
    Get full details of a Jira issue by key (e.g. ER-123, PROJ-456).
    Returns summary, description, status, comments, assignee, etc.
    """
    data = _get(f"/issue/{issue_key}", params={
        "fields": "summary,description,status,priority,assignee,reporter,"
                  "created,updated,issuetype,labels,comment,components,"
                  "fixVersions,resolution",
    })
    f = data["fields"]
    comments = []
    for c in f.get("comment", {}).get("comments", []):
        # description is ADF — extract text nodes
        body_text = _adf_to_text(c.get("body", {}))
        comments.append({
            "author": c.get("author", {}).get("displayName", ""),
            "created": c.get("created", ""),
            "body": body_text[:500],
        })

    description_text = _adf_to_text(f.get("description") or {})

    return json.dumps({
        "key": data["key"],
        "summary": f.get("summary", ""),
        "type": f.get("issuetype", {}).get("name", ""),
        "status": f.get("status", {}).get("name", ""),
        "priority": f.get("priority", {}).get("name", ""),
        "assignee": (f.get("assignee") or {}).get("displayName", "Unassigned"),
        "reporter": (f.get("reporter") or {}).get("displayName", ""),
        "labels": f.get("labels", []),
        "components": [c["name"] for c in f.get("components", [])],
        "resolution": (f.get("resolution") or {}).get("name", None),
        "created": f.get("created", ""),
        "updated": f.get("updated", ""),
        "description": description_text[:2000],
        "comments": comments[-5:],  # last 5 comments
    }, indent=2)


# ─── Create issue ────────────────────────────────────────────────────────────

def create_issue(
    project_key: str,
    summary: str,
    description: str = "",
    issue_type: str = "Task",
    priority: str = "Medium",
    labels: str = "",
    assignee_email: str = "",
) -> str:
    """
    Create a new Jira issue.

    Args:
        project_key: Project key (e.g. "ER", "PROJ")
        summary: Issue title
        description: Issue description (plain text, converted to ADF)
        issue_type: Task, Bug, Story, Epic, Sub-task
        priority: Highest, High, Medium, Low, Lowest
        labels: Comma-separated labels (e.g. "ai,poc,l3")
        assignee_email: Assignee email (leave empty for unassigned)
    """
    body: dict = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }
    }
    if description:
        body["fields"]["description"] = _text_to_adf(description)
    if labels:
        body["fields"]["labels"] = [l.strip() for l in labels.split(",") if l.strip()]
    if assignee_email:
        # Look up accountId by email
        users = _get("/user/search", params={"query": assignee_email, "maxResults": 1})
        if users:
            body["fields"]["assignee"] = {"accountId": users[0]["accountId"]}

    result = _post("/issue", body)
    return json.dumps({
        "created": True,
        "key": result["key"],
        "id": result["id"],
        "url": f"{JIRA_URL}/browse/{result['key']}",
    }, indent=2)


# ─── Update issue ────────────────────────────────────────────────────────────

def update_issue(
    issue_key: str,
    summary: str = "",
    description: str = "",
    priority: str = "",
    labels: str = "",
    assignee_email: str = "",
) -> str:
    """
    Update fields on an existing Jira issue.
    Only non-empty fields are updated — others are left unchanged.

    Args:
        issue_key: Issue key (e.g. "ER-123")
        summary: New title (leave empty to keep current)
        description: New description (leave empty to keep current)
        priority: New priority (leave empty to keep current)
        labels: New comma-separated labels (leave empty to keep current)
        assignee_email: New assignee email (leave empty to keep current)
    """
    fields: dict = {}
    if summary:
        fields["summary"] = summary
    if description:
        fields["description"] = _text_to_adf(description)
    if priority:
        fields["priority"] = {"name": priority}
    if labels:
        fields["labels"] = [l.strip() for l in labels.split(",") if l.strip()]
    if assignee_email:
        users = _get("/user/search", params={"query": assignee_email, "maxResults": 1})
        if users:
            fields["assignee"] = {"accountId": users[0]["accountId"]}

    if not fields:
        return json.dumps({"error": "No fields to update — pass at least one non-empty field"})

    _put(f"/issue/{issue_key}", {"fields": fields})
    return json.dumps({
        "updated": True,
        "key": issue_key,
        "url": f"{JIRA_URL}/browse/{issue_key}",
        "fields_updated": list(fields.keys()),
    }, indent=2)


# ─── Transition (change status) ──────────────────────────────────────────────

def transition_issue(issue_key: str, status_name: str) -> str:
    """
    Change the status of a Jira issue (e.g. "In Progress", "Done", "To Do").

    Args:
        issue_key: Issue key (e.g. "ER-123")
        status_name: Target status name (e.g. "In Progress", "Done")
    """
    # Get available transitions
    t_data = _get(f"/issue/{issue_key}/transitions")
    transitions = t_data.get("transitions", [])

    match = next(
        (t for t in transitions if t["name"].lower() == status_name.lower()),
        None,
    )
    if not match:
        available = [t["name"] for t in transitions]
        return json.dumps({
            "error": f"Status '{status_name}' not available for {issue_key}",
            "available_transitions": available,
        }, indent=2)

    r = httpx.post(
        f"{_BASE}/issue/{issue_key}/transitions",
        headers=_headers(),
        json={"transition": {"id": match["id"]}},
        timeout=30.0,
    )
    r.raise_for_status()
    return json.dumps({
        "transitioned": True,
        "key": issue_key,
        "new_status": status_name,
        "url": f"{JIRA_URL}/browse/{issue_key}",
    }, indent=2)


# ─── Add comment ─────────────────────────────────────────────────────────────

def add_comment(issue_key: str, comment_text: str) -> str:
    """
    Add a comment to a Jira issue.

    Args:
        issue_key: Issue key (e.g. "ER-123")
        comment_text: The comment text (plain text)
    """
    body = {"body": _text_to_adf(comment_text)}
    result = _post(f"/issue/{issue_key}/comment", body)
    return json.dumps({
        "commented": True,
        "key": issue_key,
        "comment_id": result.get("id"),
        "url": f"{JIRA_URL}/browse/{issue_key}",
    }, indent=2)


# ─── Assign issue ────────────────────────────────────────────────────────────

def assign_issue(issue_key: str, assignee_email: str) -> str:
    """
    Assign a Jira issue to a user by their email address.

    Args:
        issue_key: Issue key (e.g. "ER-123")
        assignee_email: Assignee's email (e.g. "ssingh@acs-i.org")
    """
    users = _get("/user/search", params={"query": assignee_email, "maxResults": 1})
    if not users:
        return json.dumps({"error": f"No user found for email: {assignee_email}"})

    account_id = users[0]["accountId"]
    r = httpx.put(
        f"{_BASE}/issue/{issue_key}/assignee",
        headers=_headers(),
        json={"accountId": account_id},
        timeout=30.0,
    )
    r.raise_for_status()
    return json.dumps({
        "assigned": True,
        "key": issue_key,
        "assignee": users[0].get("displayName", assignee_email),
        "url": f"{JIRA_URL}/browse/{issue_key}",
    }, indent=2)


# ─── My open issues ─────────────────────────────────────────────────────────

def my_open_issues() -> str:
    """Get all open issues assigned to the current user."""
    return search_issues(
        jql='assignee = currentUser() AND statusCategory != "Done" ORDER BY priority DESC, updated DESC',
        max_results=30,
    )


# ─── Sprint info ─────────────────────────────────────────────────────────────

def get_board_sprints(board_id: str) -> str:
    """
    Get active and future sprints for a Scrum/Kanban board.

    Args:
        board_id: The Jira board ID (number). Find it in the board URL.
    """
    r = httpx.get(
        f"{JIRA_URL}/rest/agile/1.0/board/{board_id}/sprint",
        headers=_headers(),
        params={"state": "active,future", "maxResults": 5},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    sprints = []
    for s in data.get("values", []):
        sprints.append({
            "id": s["id"],
            "name": s["name"],
            "state": s["state"],
            "startDate": s.get("startDate", ""),
            "endDate": s.get("endDate", ""),
            "goal": s.get("goal", ""),
        })
    return json.dumps(sprints, indent=2)


# ─── ADF helpers ─────────────────────────────────────────────────────────────

def _text_to_adf(text: str) -> dict:
    """Convert plain text to Atlassian Document Format (ADF)."""
    paragraphs = []
    for para in text.split("\n\n"):
        lines = para.strip().split("\n")
        content = []
        for line in lines:
            if content:
                content.append({"type": "hardBreak"})
            content.append({"type": "text", "text": line})
        if content:
            paragraphs.append({"type": "paragraph", "content": content})
    return {
        "version": 1,
        "type": "doc",
        "content": paragraphs or [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _adf_to_text(adf: dict) -> str:
    """Recursively extract plain text from ADF (Atlassian Document Format)."""
    if not adf or not isinstance(adf, dict):
        return ""
    parts = []
    if adf.get("type") == "text":
        return adf.get("text", "")
    if adf.get("type") == "hardBreak":
        return "\n"
    for child in adf.get("content", []):
        parts.append(_adf_to_text(child))
    return "".join(parts)







