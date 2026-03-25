"""
Jira MCP Server
────────────────
Exposes Jira as MCP tools for Claude Desktop, VS Code Copilot, or any MCP client.

Two modes:
  1. FastMCP (stdio/SSE) →  python mcp_server.py --fastmcp
  2. Gradio  (UI + MCP)  →  python mcp_server.py

Env vars (set in .env or shell):
  JIRA_URL         https://your-org.atlassian.net
  JIRA_EMAIL       you@company.com
  JIRA_API_TOKEN   your-token
"""

import argparse
import logging
import os
import sys

logger = logging.getLogger(__name__)

# ─── Import Jira tool implementations ────────────────────────────────────────

from jira_client import (
    server_info as _server_info,
    myself as _myself,
    list_projects as _list_projects,
    search_issues as _search_issues,
    get_issue as _get_issue,
    create_issue as _create_issue,
    update_issue as _update_issue,
    transition_issue as _transition_issue,
    add_comment as _add_comment,
    assign_issue as _assign_issue,
    my_open_issues as _my_open_issues,
    get_board_sprints as _get_board_sprints,
    get_sprint_issues as _get_sprint_issues,
    get_transitions as _get_transitions,
    link_issues as _link_issues,
    create_subtask as _create_subtask,
    add_labels as _add_labels,
    remove_labels as _remove_labels,
    log_work as _log_work,
    add_watcher as _add_watcher,
    get_issue_changelog as _get_issue_changelog,
    search_users as _search_users,
    delete_issue as _delete_issue,
)


# ═════════════════════════════════════════════════════════════════════════════
#  MODE 1: Gradio MCP Server (Web UI + MCP endpoint)
# ═════════════════════════════════════════════════════════════════════════════

def run_gradio_mcp():
    """Launch Gradio UI with mcp_server=True — tools exposed via MCP + web UI."""
    import gradio as gr

    def list_projects() -> str:
        """List all Jira projects you have access to."""
        return _list_projects()

    def search_issues(jql: str, max_results: int = 20) -> str:
        """Search Jira issues using JQL. Example: project = ER AND status = 'In Progress'"""
        return _search_issues(jql=jql, max_results=max_results)

    def get_issue(issue_key: str) -> str:
        """Get full details of a Jira issue (e.g. ER-123)."""
        return _get_issue(issue_key=issue_key)

    def create_issue(
        project_key: str,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
        priority: str = "Medium",
        labels: str = "",
    ) -> str:
        """Create a new Jira issue."""
        return _create_issue(
            project_key=project_key, summary=summary, description=description,
            issue_type=issue_type, priority=priority, labels=labels,
        )

    def add_comment(issue_key: str, comment_text: str) -> str:
        """Add a comment to a Jira issue."""
        return _add_comment(issue_key=issue_key, comment_text=comment_text)

    def transition_issue(issue_key: str, status_name: str) -> str:
        """Change issue status (e.g. 'In Progress', 'Done')."""
        return _transition_issue(issue_key=issue_key, status_name=status_name)

    def my_open_issues() -> str:
        """Get all open issues assigned to me."""
        return _my_open_issues()

    with gr.Blocks(title="Jira MCP Server") as demo:
        gr.Markdown("# 🎫 Jira MCP Server")
        gr.Markdown(
            "All tools below are exposed via **MCP** for Claude Desktop / VS Code Copilot / any agent.\n\n"
            f"Connected to: **{os.getenv('JIRA_URL', '(not configured)')}**"
        )

        with gr.Tab("🔍 Search (JQL)"):
            gr.Interface(
                fn=search_issues,
                inputs=[
                    gr.Textbox(label="JQL Query", placeholder='project = ER AND status = "To Do"'),
                    gr.Number(label="Max Results", value=20),
                ],
                outputs=gr.JSON(),
                title="Search Issues",
                api_name="search_issues",
            )

        with gr.Tab("📄 Get Issue"):
            gr.Interface(
                fn=get_issue,
                inputs=[gr.Textbox(label="Issue Key", placeholder="ER-123")],
                outputs=gr.JSON(),
                title="Get Issue Details",
                api_name="get_issue",
            )

        with gr.Tab("📋 Projects"):
            gr.Interface(
                fn=list_projects,
                inputs=[],
                outputs=gr.JSON(),
                title="List Projects",
                api_name="list_projects",
            )

        with gr.Tab("➕ Create Issue"):
            gr.Interface(
                fn=create_issue,
                inputs=[
                    gr.Textbox(label="Project Key", placeholder="ER"),
                    gr.Textbox(label="Summary", placeholder="Issue title"),
                    gr.Textbox(label="Description", placeholder="Details...", lines=3),
                    gr.Dropdown(choices=["Task", "Bug", "Story", "Epic"], value="Task", label="Type"),
                    gr.Dropdown(
                        choices=["Highest", "High", "Medium", "Low", "Lowest"],
                        value="Medium", label="Priority",
                    ),
                    gr.Textbox(label="Labels (comma-sep)", placeholder="ai,poc"),
                ],
                outputs=gr.JSON(),
                title="Create Issue",
                api_name="create_issue",
            )

        with gr.Tab("💬 Add Comment"):
            gr.Interface(
                fn=add_comment,
                inputs=[
                    gr.Textbox(label="Issue Key", placeholder="ER-123"),
                    gr.Textbox(label="Comment", placeholder="Your comment...", lines=3),
                ],
                outputs=gr.JSON(),
                title="Add Comment",
                api_name="add_comment",
            )

        with gr.Tab("🔄 Change Status"):
            gr.Interface(
                fn=transition_issue,
                inputs=[
                    gr.Textbox(label="Issue Key", placeholder="ER-123"),
                    gr.Textbox(label="New Status", placeholder="In Progress"),
                ],
                outputs=gr.JSON(),
                title="Transition Issue",
                api_name="transition_issue",
            )

        with gr.Tab("👤 My Issues"):
            gr.Interface(
                fn=my_open_issues,
                inputs=[],
                outputs=gr.JSON(),
                title="My Open Issues",
                api_name="my_open_issues",
            )

    port = int(os.getenv("MCP_PORT", "7861"))
    demo.launch(
        share=False,
        server_name="0.0.0.0",
        server_port=port,
        mcp_server=True,
        show_api=True,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  MODE 2: FastMCP Server (lightweight, no UI — for Claude Desktop / Copilot)
# ═════════════════════════════════════════════════════════════════════════════

def run_fastmcp():
    """Launch standalone MCP server via stdio or SSE."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP(
        name="jira",
        description="Jira Cloud tools — search, create, update, comment, and manage issues",
    )

    @mcp.tool()
    def server_info() -> str:
        """Get Jira server info — confirms connectivity and shows version/deployment type."""
        return _server_info()

    @mcp.tool()
    def myself() -> str:
        """Get current authenticated user info (name, email, account ID)."""
        return _myself()

    @mcp.tool()
    def list_projects() -> str:
        """List all Jira projects you have access to. Returns project key, name, type, and lead."""
        return _list_projects()

    @mcp.tool()
    def search_issues(jql: str, max_results: int = 20) -> str:
        """Search Jira issues using JQL (Jira Query Language).
        Examples:
          - project = ER AND status = "In Progress"
          - assignee = currentUser() ORDER BY priority DESC
          - text ~ "editor recommender" AND created >= -7d
          - labels = ai AND sprint in openSprints()
        """
        return _search_issues(jql=jql, max_results=max_results)

    @mcp.tool()
    def get_issue(issue_key: str) -> str:
        """Get full details of a Jira issue by its key (e.g. ER-123, PROJ-456).
        Returns summary, description, status, priority, assignee, labels, and last 5 comments."""
        return _get_issue(issue_key=issue_key)

    @mcp.tool()
    def create_issue(
        project_key: str,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
        priority: str = "Medium",
        labels: str = "",
        assignee_email: str = "",
    ) -> str:
        """Create a new Jira issue.
        Args:
            project_key: Project key (e.g. "ER", "PROJ")
            summary: Issue title / summary
            description: Detailed description (plain text)
            issue_type: Task, Bug, Story, Epic, Sub-task
            priority: Highest, High, Medium, Low, Lowest
            labels: Comma-separated labels (e.g. "ai,poc,l3")
            assignee_email: Assignee email (leave empty for unassigned)
        """
        return _create_issue(
            project_key=project_key, summary=summary, description=description,
            issue_type=issue_type, priority=priority, labels=labels,
            assignee_email=assignee_email,
        )

    @mcp.tool()
    def update_issue(
        issue_key: str,
        summary: str = "",
        description: str = "",
        priority: str = "",
        labels: str = "",
        assignee_email: str = "",
    ) -> str:
        """Update fields on an existing Jira issue. Only non-empty fields are changed.
        Args:
            issue_key: Issue key (e.g. "ER-123")
            summary: New title (leave empty to keep current)
            description: New description (leave empty to keep current)
            priority: New priority (leave empty to keep current)
            labels: New labels comma-separated (leave empty to keep current)
            assignee_email: New assignee email (leave empty to keep current)
        """
        return _update_issue(
            issue_key=issue_key, summary=summary, description=description,
            priority=priority, labels=labels, assignee_email=assignee_email,
        )

    @mcp.tool()
    def transition_issue(issue_key: str, status_name: str) -> str:
        """Change the status of a Jira issue (e.g. 'In Progress', 'Done', 'To Do').
        If the status is not available, returns the list of valid transitions."""
        return _transition_issue(issue_key=issue_key, status_name=status_name)

    @mcp.tool()
    def add_comment(issue_key: str, comment_text: str) -> str:
        """Add a comment to a Jira issue.
        Args:
            issue_key: Issue key (e.g. "ER-123")
            comment_text: The comment body (plain text)
        """
        return _add_comment(issue_key=issue_key, comment_text=comment_text)

    @mcp.tool()
    def assign_issue(issue_key: str, assignee_email: str) -> str:
        """Assign a Jira issue to a user by their email address.
        Args:
            issue_key: Issue key (e.g. "ER-123")
            assignee_email: Email of the person to assign (e.g. "ssingh@acs-i.org")
        """
        return _assign_issue(issue_key=issue_key, assignee_email=assignee_email)

    @mcp.tool()
    def my_open_issues() -> str:
        """Get all open issues currently assigned to me, ordered by priority."""
        return _my_open_issues()

    @mcp.tool()
    def get_board_sprints(board_id: str) -> str:
        """Get active and upcoming sprints for a Jira board.
        Args:
            board_id: The board ID (number from the board URL)
        """
        return _get_board_sprints(board_id=board_id)

    @mcp.tool()
    def get_sprint_issues(sprint_id: str, max_results: int = 30) -> str:
        """Get all issues in a specific sprint.
        Args:
            sprint_id: The sprint ID (get it from get_board_sprints)
            max_results: Maximum issues to return (default 30)
        """
        return _get_sprint_issues(sprint_id=sprint_id, max_results=max_results)

    @mcp.tool()
    def get_transitions(issue_key: str) -> str:
        """Get all available status transitions for an issue.
        Use this to find valid status names before calling transition_issue.
        Args:
            issue_key: Issue key (e.g. "ENG-123")
        """
        return _get_transitions(issue_key=issue_key)

    @mcp.tool()
    def link_issues(inward_key: str, outward_key: str, link_type: str = "Relates") -> str:
        """Link two Jira issues together.
        Args:
            inward_key: Source issue (e.g. "ENG-100")
            outward_key: Target issue (e.g. "ENG-200")
            link_type: Relates (default), Blocks, Cloners, Duplicate
        """
        return _link_issues(inward_key=inward_key, outward_key=outward_key, link_type=link_type)

    @mcp.tool()
    def create_subtask(
        parent_key: str,
        summary: str,
        description: str = "",
        priority: str = "Medium",
        assignee_email: str = "",
    ) -> str:
        """Create a subtask under an existing issue.
        Args:
            parent_key: Parent issue key (e.g. "ENG-123")
            summary: Subtask title
            description: Subtask description (plain text)
            priority: Highest, High, Medium, Low, Lowest
            assignee_email: Assignee email (leave empty for unassigned)
        """
        return _create_subtask(
            parent_key=parent_key, summary=summary, description=description,
            priority=priority, assignee_email=assignee_email,
        )

    @mcp.tool()
    def add_labels(issue_key: str, labels: str) -> str:
        """Add labels to an issue without removing existing ones.
        Args:
            issue_key: Issue key (e.g. "ENG-123")
            labels: Comma-separated labels (e.g. "ai,poc,urgent")
        """
        return _add_labels(issue_key=issue_key, labels=labels)

    @mcp.tool()
    def remove_labels(issue_key: str, labels: str) -> str:
        """Remove specific labels from an issue.
        Args:
            issue_key: Issue key (e.g. "ENG-123")
            labels: Comma-separated labels to remove (e.g. "old-label,deprecated")
        """
        return _remove_labels(issue_key=issue_key, labels=labels)

    @mcp.tool()
    def log_work(issue_key: str, time_spent: str, comment: str = "") -> str:
        """Log time spent on an issue (time tracking).
        Args:
            issue_key: Issue key (e.g. "ENG-123")
            time_spent: Time in Jira format (e.g. "2h", "1d", "30m", "1h 30m")
            comment: Optional description of work done
        """
        return _log_work(issue_key=issue_key, time_spent=time_spent, comment=comment)

    @mcp.tool()
    def add_watcher(issue_key: str, watcher_email: str) -> str:
        """Add a watcher to an issue so they receive notifications.
        Args:
            issue_key: Issue key (e.g. "ENG-123")
            watcher_email: Email of the person to add as watcher
        """
        return _add_watcher(issue_key=issue_key, watcher_email=watcher_email)

    @mcp.tool()
    def get_issue_changelog(issue_key: str, max_results: int = 10) -> str:
        """Get the change history of an issue — who changed what and when.
        Args:
            issue_key: Issue key (e.g. "ENG-123")
            max_results: Maximum history entries (default 10)
        """
        return _get_issue_changelog(issue_key=issue_key, max_results=max_results)

    @mcp.tool()
    def search_users(query: str, max_results: int = 10) -> str:
        """Search for Jira users by name or email.
        Args:
            query: Name or email to search (e.g. "singh" or "ssingh@acs-i.org")
            max_results: Maximum results (default 10)
        """
        return _search_users(query=query, max_results=max_results)

    @mcp.tool()
    def delete_issue(issue_key: str, delete_subtasks: bool = False) -> str:
        """Delete a Jira issue. WARNING: cannot be undone.
        Args:
            issue_key: Issue key (e.g. "ENG-123")
            delete_subtasks: If true, also deletes all subtasks
        """
        return _delete_issue(issue_key=issue_key, delete_subtasks=delete_subtasks)

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        port = int(os.getenv("MCP_PORT", "7861"))
        logger.info("Starting Jira MCP server (SSE) on port %d", port)
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        mcp.run(transport="stdio")


# ─── Main ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[Jira MCP] %(message)s")

    parser = argparse.ArgumentParser(description="Jira MCP Server")
    parser.add_argument(
        "--fastmcp", action="store_true",
        help="Use FastMCP (stdio/SSE) instead of Gradio",
    )
    args = parser.parse_args()

    if args.fastmcp:
        print("Starting Jira FastMCP server...")
        run_fastmcp()
    else:
        print("Starting Jira Gradio MCP server...")
        run_gradio_mcp()




