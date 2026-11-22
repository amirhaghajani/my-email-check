"""Thin wrapper around exchangelib for an on-premises mailbox accessed via impersonation."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from exchangelib import (
    BASIC,
    DELEGATE,
    GSSAPI,
    IMPERSONATION,
    NTLM,
    Account,
    Configuration,
    Credentials,
    Mailbox,
    Message,
    Q,
)
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
from exchangelib.services import ResolveNames

from .config import Settings

_AUTH_TYPES = {"NTLM": NTLM, "BASIC": BASIC, "GSSAPI": GSSAPI}
_ACCESS_TYPES = {"IMPERSONATION": IMPERSONATION, "DELEGATE": DELEGATE}


def item_id(item: Any) -> str:
    return getattr(item, "id", None) or ""


class ExchangeClient:
    def __init__(self, settings: Settings, username: str, password: str) -> None:
        self.settings = settings
        self.settings.require_exchange()
        if not username or not password:
            raise ValueError("Exchange username and password are required")

        if not self.settings.exchange_verify_ssl:
            # Deliberate opt-in: internal CA. Warn loudly in the CLI.
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

        credentials = Credentials(
            username=username,
            password=password,
        )
        auth_type = _AUTH_TYPES[self.settings.exchange_auth_type.upper()]
        access_type = _ACCESS_TYPES[self.settings.exchange_access_type.upper()]

        if self.settings.exchange_ews_url:
            config = Configuration(
                service_endpoint=self.settings.exchange_ews_url,
                credentials=credentials,
                auth_type=auth_type,
            )
            self.account = Account(
                primary_smtp_address=self.settings.mailbox_email,
                config=config,
                access_type=access_type,
            )
        elif self.settings.exchange_autodiscover:
            self.account = Account(
                primary_smtp_address=self.settings.mailbox_email,
                credentials=credentials,
                autodiscover=True,
                access_type=access_type,
            )
        else:
            config = Configuration(
                server=self.settings.exchange_server,
                credentials=credentials,
                auth_type=auth_type,
            )
            self.account = Account(
                primary_smtp_address=self.settings.mailbox_email,
                config=config,
                autodiscover=False,
                access_type=access_type,
            )
        self._item_cache: dict[str, Any] = {}

    # -- folders / search -------------------------------------------------
    def get_folder(self, folder: str) -> Any:
        name = (folder or "sentitems").lower()
        if name in ("sent", "sentitems"):
            return self.account.sent
        if name == "inbox":
            return self.account.inbox
        if name in ("all", "root", "msg_folder_root"):
            return self.account.msg_folder_root
        raise ValueError(f"Unknown folder: {folder!r}")

    def search(
        self,
        folder: str = "sentitems",
        since: datetime | None = None,
        until: datetime | None = None,
        subject_contains: str | None = None,
        limit: int = 25,
        fetch_body: bool = False,
    ) -> list[Any]:
        qs = self.get_folder(folder)

        filters: list[Q] = []
        if since is not None:
            filters.append(Q(datetime_sent__gte=since))
        if until is not None:
            filters.append(Q(datetime_sent__lte=until))
        if subject_contains:
            filters.append(Q(subject__contains=subject_contains))
        if filters:
            combined = filters[0]
            for extra in filters[1:]:
                combined = combined & extra
            qs = qs.filter(combined)

        fields = [
            "subject",
            "sender",
            "to_recipients",
            "cc_recipients",
            "datetime_sent",
            "has_attachments",
        ]
        if fetch_body:
            fields.append("text_body")
        qs = qs.only(*fields).order_by("-datetime_sent")[: max(1, limit)]

        items = list(qs)
        for item in items:
            self._item_cache[item_id(item)] = item
        return items

    def get_item(self, item_id_value: str) -> Any:
        cached = self._item_cache.get(item_id_value)
        if cached is not None:
            return cached
        item = next(iter(self.account.fetch(ids=[(item_id_value, None)])))
        self._item_cache[item_id_value] = item
        return item

    def resolve_names(self, name: str) -> list[Any]:
        return list(ResolveNames(account=self.account).call(unresolved_entries=[name]))

    # -- messages ---------------------------------------------------------
    def create_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> Message:
        msg = Message(
            account=self.account,
            subject=subject,
            body=body,
            to_recipients=[Mailbox(email_address=addr) for addr in to],
        )
        if cc:
            msg.cc_recipients = [Mailbox(email_address=addr) for addr in cc]
        if bcc:
            msg.bcc_recipients = [Mailbox(email_address=addr) for addr in bcc]
        return msg

    def send(self, message: Message) -> str:
        message.send()
        return item_id(message)

    # -- diagnostics ------------------------------------------------------
    def counts(self) -> dict[str, int]:
        return {
            "inbox": self.account.inbox.total_count,
            "sent": self.account.sent.total_count,
        }

    def mailbox(self) -> str:
        return self.account.primary_smtp_address