"""In-process tools exposed to the agent (and mirrored as an MCP server).

Each method is self-contained and returns JSON-serialisable data. Secret values
are masked before leaving the tool unless ``REPORT_SHOW_SECRETS`` is true.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from exchangelib import Message

from .backend import MailboxBackend, build_backend
from .config import Settings, get_settings
from .exchange_client import item_id
from .output import console, redact, redact_value, safe_output_path

ConfirmFn = Callable[[str], bool]


def _parse_dt(value: Any, default_tz: Any = None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None and default_tz is not None:
        try:
            dt = default_tz.localize(dt)
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _mailbox_strings(mailboxes: Any) -> list[str]:
    out: list[str] = []
    for m in mailboxes or []:
        name = getattr(m, "name", None)
        email = getattr(m, "email_address", None)
        if name and email:
            out.append(f"{name} <{email}>")
        elif email:
            out.append(email)
        elif name:
            out.append(name)
    return [x for x in out if x]


def _contains(haystack: str | None, needle: str | None) -> bool:
    if not needle:
        return True
    return needle.lower() in (haystack or "").lower()


class ToolBox:
    def __init__(
        self,
        settings: Settings | None = None,
        username: str = "",
        password: str = "",
        backend: MailboxBackend | None = None,
        confirm: ConfirmFn | None = None,
        defer_send: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.username = username
        self.password = password
        self._backend = backend
        self.drafts: dict[str, Message] = {}
        self._confirm = confirm or self._default_confirm
        self.defer_send = defer_send

    @property
    def backend(self) -> MailboxBackend:
        if self._backend is None:
            self._backend = build_backend(self.settings, self.username, self.password)
        return self._backend

    def _default_confirm(self, summary: str) -> bool:
        if self.settings.send_auto_approve:
            return True
        answer = input(f"{summary}\nSend this email? [y/N] ").strip().lower()
        return answer in ("y", "yes")

    # -- tools ------------------------------------------------------------
    def resolve_recipient(self, name: str) -> list[dict[str, str]]:
        """Resolve a human name or partial address to concrete mailboxes.

        Use this first when the user names a person (e.g. "Mr Bala Bala") so
        later searches use a real email address.
        """
        results = self.backend.resolve_names(name)
        out = []
        for m in results:
            email = getattr(m, "email_address", "") or ""
            display = getattr(m, "name", "") or ""
            mtype = getattr(m, "mailbox_type", None) or "mailbox"
            if email:
                out.append({"name": display, "email": email, "type": str(mtype)})
        return redact_value(out, self.settings.report_show_secrets)

    def search_emails(
        self,
        to: str | None = None,
        from_: str | None = None,
        subject_contains: str | None = None,
        body_contains: str | None = None,
        since: str | None = None,
        until: str | None = None,
        folder: str = "sentitems",
        limit: int = 25,
        has_attachments: bool | None = None,
        preview: bool = False,
    ) -> list[dict[str, Any]]:
        """Search the mailbox and return email summaries (id, subject, people, date).

        folder: "sentitems" (default), "inbox", or "all".
        Dates are ISO strings (e.g. "2025-01-01"). Recipient/sender/body text
        filters are applied client-side because EWS recipient search is unreliable.
        Set preview=True to include a short body snippet (fetches message bodies).
        """
        client = self.backend
        default_tz = getattr(getattr(client, "account", None), "default_timezone", None)
        since_dt = _parse_dt(since, default_tz)
        until_dt = _parse_dt(until, default_tz)
        if until_dt is not None and isinstance(until, str) and "T" not in until and " " not in until:
            # date-only "until" means end of that day
            until_dt = until_dt + timedelta(days=1)

        need_body = bool(preview) or bool(body_contains)
        items = client.search(
            folder=folder,
            since=since_dt,
            until=until_dt,
            subject_contains=subject_contains,
            limit=max(1, min(int(limit or 25), 200)),
            fetch_body=need_body,
        )

        results: list[dict[str, Any]] = []
        for item in items:
            to_list = _mailbox_strings(getattr(item, "to_recipients", None))
            cc_list = _mailbox_strings(getattr(item, "cc_recipients", None))
            sender = _mailbox_strings([getattr(item, "sender", None)])
            sender_str = sender[0] if sender else ""

            to_blob = " ".join(to_list + cc_list)
            if not _contains(to_blob, to):
                continue
            if not _contains(sender_str, from_):
                continue
            if has_attachments is not None and bool(getattr(item, "has_attachments", False)) != has_attachments:
                continue

            body = (getattr(item, "text_body", None) or "") if need_body else ""
            if body_contains and body_contains.lower() not in body.lower():
                continue

            sent = getattr(item, "datetime_sent", None)
            results.append(
                {
                    "item_id": item_id(item),
                    "subject": redact(
                        getattr(item, "subject", "") or "", self.settings.report_show_secrets
                    ),
                    "from": sender_str,
                    "to": to_list,
                    "cc": cc_list,
                    "datetime_sent": sent.isoformat() if sent else None,
                    "has_attachments": bool(getattr(item, "has_attachments", False)),
                    "preview": redact(body[:400], self.settings.report_show_secrets) if preview else "",
                }
            )

        return results

    def read_email(
        self,
        item_id: str,
        include_body: bool = True,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        """Read one email by its item_id (from search_emails). Returns headers and body text."""
        item = self.backend.get_item(item_id)
        body = ""
        if include_body:
            raw = getattr(item, "text_body", None) or ""
            body = raw[: max(1, int(max_body_chars or 4000))]
        attachments = [getattr(a, "name", "") for a in (getattr(item, "attachments", None) or [])]
        sent = getattr(item, "datetime_sent", None)
        out = {
            "item_id": item_id,
            "subject": getattr(item, "subject", "") or "",
            "from": _mailbox_strings([getattr(item, "sender", None)]),
            "to": _mailbox_strings(getattr(item, "to_recipients", None)),
            "cc": _mailbox_strings(getattr(item, "cc_recipients", None)),
            "datetime_sent": sent.isoformat() if sent else None,
            "attachments": [a for a in attachments if a],
            "body": redact(body, self.settings.report_show_secrets),
        }
        return out

    def create_email(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> str:
        """Create (but do NOT send) an email draft. Returns a draft_id for send_email."""
        if not to:
            raise ValueError("At least one recipient is required")
        msg = self.backend.create_message(to=to, subject=subject, body=body, cc=cc, bcc=bcc)
        draft_id = uuid.uuid4().hex[:12]
        self.drafts[draft_id] = msg
        return draft_id

    def send_email(self, draft_id: str) -> dict[str, Any]:
        """Send a draft created by create_email. ALWAYS asks the user to confirm first."""
        msg = self.drafts.get(draft_id)
        if msg is None:
            return {"sent": False, "reason": f"Unknown draft_id: {draft_id}"}

        to = _mailbox_strings(getattr(msg, "to_recipients", None))
        summary = (
            f"To: {', '.join(to)}\n"
            f"Subject: {getattr(msg, 'subject', '') or ''}\n"
            f"Body:\n{getattr(msg, 'text_body', '') or ''}"
        )
        console.print("--- Draft to send (secrets not masked for your review) ---")
        console.print(summary)
        console.print("---------------------------------------------------------")

        if self.defer_send:
            return {
                "sent": False,
                "reason": "awaiting_confirmation",
                "draft_id": draft_id,
                "summary": summary,
            }

        if not self._confirm(summary):
            return {"sent": False, "reason": "user declined"}

        new_id = self.backend.send(msg)
        self.drafts.pop(draft_id, None)
        return {"sent": True, "message_id": new_id}

    def draft_summaries(self) -> list[dict[str, Any]]:
        """List pending drafts (used by the web UI's confirmation panel)."""
        out: list[dict[str, Any]] = []
        for draft_id, msg in self.drafts.items():
            out.append(
                {
                    "draft_id": draft_id,
                    "to": _mailbox_strings(getattr(msg, "to_recipients", None)),
                    "subject": getattr(msg, "subject", "") or "",
                    "body": getattr(msg, "text_body", "") or "",
                }
            )
        return out

    def send_draft_now(self, draft_id: str) -> dict[str, Any]:
        """Send a pending draft after explicit user confirmation in the UI."""
        msg = self.drafts.pop(draft_id, None)
        if msg is None:
            return {"sent": False, "reason": f"Unknown draft_id: {draft_id}"}
        new_id = self.backend.send(msg)
        return {"sent": True, "message_id": new_id}

    def write_text_file(self, path: str, content: str, append: bool = False) -> dict[str, Any]:
        """Write UTF-8 text to a file under the reports directory (no path traversal)."""
        target = safe_output_path(path, self.settings)
        mode = "a" if append else "w"
        with open(target, mode, encoding="utf-8") as fh:
            fh.write(content)
        return {"path": str(target), "bytes": len(content.encode("utf-8"))}


def build_tools(toolbox: ToolBox) -> list[Any]:
    """Wrap ToolBox methods as LlamaIndex FunctionTools."""
    from llama_index.core.tools import FunctionTool

    specs = [
        (toolbox.resolve_recipient, "resolve_recipient"),
        (toolbox.search_emails, "search_emails"),
        (toolbox.read_email, "read_email"),
        (toolbox.create_email, "create_email"),
        (toolbox.send_email, "send_email"),
        (toolbox.write_text_file, "write_text_file"),
    ]
    return [FunctionTool.from_defaults(fn=fn, name=name) for fn, name in specs]