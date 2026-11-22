"""FastMCP (MCP) server exposing the same tools as the in-process agent.

Run standalone for external MCP clients or debugging:

    uv run mcp dev src/mailagent/exchange_mcp_server.py
    # or
    uv run python -m mailagent.exchange_mcp_server

The CLI uses the tools in-process so send_email can prompt for confirmation.
When consumed over MCP, set SEND_AUTO_APPROVE=true (its stdin is the protocol
channel, so it cannot prompt a human).
"""

from __future__ import annotations

import os

from mcp.server import MCPServer

from .config import get_settings
from .tools import ToolBox

_TOOL_METHODS = (
    "resolve_recipient",
    "search_emails",
    "scan_emails_for_secrets",
    "read_email",
    "create_email",
    "send_email",
    "write_text_file",
)


def _mcp_confirm(summary: str) -> bool:
    """MCP stdio has no human on stdin; require explicit opt-in to send."""
    settings = get_settings()
    if settings.send_auto_approve:
        return True
    raise RuntimeError(
        "send_email needs human confirmation, which is unavailable over MCP stdio. "
        "Set SEND_AUTO_APPROVE=true to allow sending, or use the interactive CLI."
    )


def build_server() -> MCPServer:
    settings = get_settings()
    # MCP mode has no interactive terminal. EWS needs credentials from env vars;
    # the Outlook backend uses the local profile and needs none.
    username = os.environ.get("EXCHANGE_USERNAME", "").strip()
    password = os.environ.get("EXCHANGE_PASSWORD", "")
    if settings.mail_backend.lower() == "ews" and (not username or not password):
        raise RuntimeError(
            "MCP mode with the EWS backend requires EXCHANGE_USERNAME and "
            "EXCHANGE_PASSWORD environment variables (it cannot prompt)."
        )
    box = ToolBox(
        settings=settings,
        username=username,
        password=password,
        confirm=_mcp_confirm,
    )
    server = MCPServer("mailagent-exchange")
    for name in _TOOL_METHODS:
        server.add_tool(getattr(box, name), name=name)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()