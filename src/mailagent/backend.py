"""Mailbox backend abstraction and factory.

Two backends are supported:
- ``ews``: on-prem Exchange Web Services via exchangelib (service account).
- ``outlook``: the locally installed Outlook profile via COM (MAPI/HTTP).
"""

from __future__ import annotations

from typing import Any, Protocol

from .config import Settings


class MailboxBackend(Protocol):
    def resolve_names(self, name: str) -> list[Any]: ...

    def search(
        self,
        folder: str = "sentitems",
        since: Any = None,
        until: Any = None,
        subject_contains: str | None = None,
        limit: int = 25,
        fetch_body: bool = False,
    ) -> list[Any]: ...

    def get_item(self, item_id: str) -> Any: ...

    def create_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> Any: ...

    def send(self, message: Any) -> str: ...

    def counts(self) -> dict[str, int]: ...

    def mailbox(self) -> str: ...


def build_backend(settings: Settings, username: str = "", password: str = "") -> MailboxBackend:
    backend = (settings.mail_backend or "ews").lower()
    if backend == "outlook":
        from .outlook_backend import OutlookBackend

        return OutlookBackend()
    if backend == "ews":
        from .exchange_client import ExchangeClient

        return ExchangeClient(settings, username, password)
    raise ValueError(f"Unknown mail backend: {backend!r} (expected 'ews' or 'outlook')")