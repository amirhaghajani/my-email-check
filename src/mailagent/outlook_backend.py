"""Outlook COM backend.

Uses the locally installed, already-configured Outlook profile (which typically
speaks MAPI/HTTP or RPC/HTTP) through COM automation. No Exchange password is
needed. This is desktop-only and runs as the current Windows user; it does not
support service-account impersonation.

The objects returned here mimic the exchangelib item shape used by tools.py
(``id``, ``subject``, ``sender``, ``to_recipients``, ``text_body`` ...).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import win32com.client

OL_MAIL_ITEM = 0
OL_FOLDER_INBOX = 6
OL_FOLDER_SENT = 18
OL_TO = 1
OL_CC = 2
OL_BCC = 3


class SimpleMailbox:
    def __init__(self, name: str = "", email_address: str = "") -> None:
        self.name = name
        self.email_address = email_address


class SimpleAttachment:
    def __init__(self, name: str = "") -> None:
        self.name = name


class SimpleItem:
    def __init__(
        self,
        id: str,
        subject: str = "",
        sender: SimpleMailbox | None = None,
        to_recipients: list[SimpleMailbox] | None = None,
        cc_recipients: list[SimpleMailbox] | None = None,
        datetime_sent: datetime | None = None,
        has_attachments: bool = False,
        text_body: str = "",
        attachments: list[SimpleAttachment] | None = None,
    ) -> None:
        self.id = id
        self.subject = subject
        self.sender = sender
        self.to_recipients = to_recipients or []
        self.cc_recipients = cc_recipients or []
        self.datetime_sent = datetime_sent
        self.has_attachments = has_attachments
        self.text_body = text_body
        self.attachments = attachments or []


class SimpleMessage:
    def __init__(
        self,
        com_item: Any,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> None:
        self._com = com_item
        self.subject = subject
        self.text_body = body
        self.to_recipients = [SimpleMailbox(a, a) for a in to]
        self.cc_recipients = [SimpleMailbox(a, a) for a in (cc or [])]
        self.bcc_recipients = [SimpleMailbox(a, a) for a in (bcc or [])]


def _smtp(recipient: Any) -> str:
    try:
        user = recipient.AddressEntry.GetExchangeUser()
        smtp = getattr(user, "PrimarySmtpAddress", "") if user is not None else ""
        if smtp:
            return smtp
    except Exception:
        pass
    try:
        return recipient.Address or ""
    except Exception:
        return ""


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second)
    except Exception:
        return None


def _outlook_date(value: datetime) -> str:
    return value.strftime("%m/%d/%Y %H:%M")


class OutlookBackend:
    def __init__(self) -> None:
        # Outlook COM is apartment-bound; keep one Application/Namespace per thread.
        import threading

        self._local = threading.local()

    def _ensure(self) -> tuple[Any, Any]:
        ns = getattr(self._local, "ns", None)
        if ns is None:
            import pythoncom

            pythoncom.CoInitialize()
            app = win32com.client.Dispatch("Outlook.Application")
            self._local.app = app
            self._local.ns = app.GetNamespace("MAPI")
        return self._local.app, self._local.ns

    @property
    def _app(self) -> Any:
        return self._ensure()[0]

    @property
    def _ns(self) -> Any:
        return self._ensure()[1]

    # -- folders ----------------------------------------------------------
    def _folder(self, folder: str) -> Any:
        name = (folder or "sentitems").lower()
        if name in ("sent", "sentitems"):
            return self._ns.GetDefaultFolder(OL_FOLDER_SENT)
        if name == "inbox":
            return self._ns.GetDefaultFolder(OL_FOLDER_INBOX)
        raise ValueError(f"Unknown folder: {folder!r}")

    # -- search -----------------------------------------------------------
    def search(
        self,
        folder: str = "sentitems",
        since: datetime | None = None,
        until: datetime | None = None,
        subject_contains: str | None = None,
        limit: int = 25,
        fetch_body: bool = False,
    ) -> list[Any]:
        if (folder or "").lower() in ("all", "root", "msg_folder_root"):
            merged: list[Any] = []
            for name in ("sentitems", "inbox"):
                merged.extend(self._search_one(name, since, until, subject_contains, limit, fetch_body))
            merged.sort(key=lambda i: i.datetime_sent or datetime.min, reverse=True)
            return merged[:limit]
        return self._search_one(folder, since, until, subject_contains, limit, fetch_body)

    def _search_one(
        self,
        folder: str,
        since: datetime | None,
        until: datetime | None,
        subject_contains: str | None,
        limit: int,
        fetch_body: bool,
    ) -> list[Any]:
        items = self._folder(folder).Items
        try:
            items.Sort("[SentOn]", True)
        except Exception:
            pass

        filters: list[str] = []
        if since is not None:
            filters.append(f"[SentOn] >= '{_outlook_date(since)}'")
        if until is not None:
            filters.append(f"[SentOn] <= '{_outlook_date(until)}'")
        if subject_contains:
            safe_subject = subject_contains.replace("'", "''")
            filters.append(f"[Subject] LIKE '%{safe_subject}'")
        if filters:
            try:
                items = items.Restrict(" AND ".join(filters))
            except Exception:
                pass

        results: list[Any] = []
        for com in items:
            try:
                item = self._to_item(com, fetch_body)
            except Exception:
                continue
            results.append(item)
            if len(results) >= max(1, limit):
                break
        return results

    def iter_items(
        self,
        folder: str = "sentitems",
        since: datetime | None = None,
        until: datetime | None = None,
        subject_contains: str | None = None,
        batch_size: int = 50,
        max_items: int | None = None,
        fetch_body: bool = True,
    ):
        items = self._folder(folder).Items
        try:
            items.Sort("[SentOn]", True)
        except Exception:
            pass

        filters: list[str] = []
        if since is not None:
            filters.append(f"[SentOn] >= '{_outlook_date(since)}'")
        if until is not None:
            filters.append(f"[SentOn] <= '{_outlook_date(until)}'")
        if subject_contains:
            safe = subject_contains.replace("'", "''")
            filters.append(f"[Subject] LIKE '%{safe}'")
        if filters:
            try:
                items = items.Restrict(" AND ".join(filters))
            except Exception:
                pass

        total = items.Count
        if max_items is not None:
            total = min(total, int(max_items))
        step = max(1, int(batch_size))
        for start in range(0, total, step):
            end = min(start + step, total)
            for index in range(start, end):
                try:
                    com = items.Item(index + 1)
                    yield self._to_item(com, fetch_body)
                except Exception:
                    continue

    def _to_item(self, com: Any, fetch_body: bool) -> SimpleItem:
        sender = SimpleMailbox(
            getattr(com, "SenderName", "") or "",
            getattr(com, "SenderEmailAddress", "") or "",
        )

        to_list: list[SimpleMailbox] = []
        cc_list: list[SimpleMailbox] = []
        try:
            for r in com.Recipients:
                mailbox = SimpleMailbox(getattr(r, "Name", "") or "", _smtp(r))
                if r.Type == OL_TO:
                    to_list.append(mailbox)
                elif r.Type == OL_CC:
                    cc_list.append(mailbox)
        except Exception:
            pass

        attachments: list[SimpleAttachment] = []
        has_attachments = False
        try:
            atts = com.Attachments
            has_attachments = atts.Count > 0
            for a in atts:
                attachments.append(
                    SimpleAttachment(getattr(a, "FileName", "") or getattr(a, "DisplayName", ""))
                )
        except Exception:
            pass

        body = ""
        if fetch_body:
            try:
                body = com.Body or ""
            except Exception:
                body = ""

        return SimpleItem(
            id=getattr(com, "EntryID", "") or "",
            subject=getattr(com, "Subject", "") or "",
            sender=sender,
            to_recipients=to_list,
            cc_recipients=cc_list,
            datetime_sent=_as_datetime(getattr(com, "SentOn", None)),
            has_attachments=has_attachments,
            text_body=body,
            attachments=attachments,
        )

    def get_item(self, item_id_value: str) -> Any:
        com = self._ns.GetItemFromID(item_id_value)
        return self._to_item(com, fetch_body=True)

    # -- recipients -------------------------------------------------------
    def resolve_names(self, name: str) -> list[Any]:
        try:
            rec = self._ns.CreateRecipient(name)
            if rec is not None and rec.Resolve():
                return [SimpleMailbox(getattr(rec, "Name", "") or name, _smtp(rec))]
        except Exception:
            pass

        results: list[Any] = []
        try:
            for address_list in self._ns.AddressLists:
                for entry in address_list.AddressEntries:
                    display = getattr(entry, "Name", "") or ""
                    address = getattr(entry, "Address", "") or ""
                    if name.lower() in display.lower() or name.lower() in address.lower():
                        results.append(SimpleMailbox(display, _smtp(entry)))
                        if len(results) >= 25:
                            return results
        except Exception:
            pass
        return results

    # -- messages ---------------------------------------------------------
    def create_message(
        self,
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> SimpleMessage:
        msg = self._app.CreateItem(OL_MAIL_ITEM)
        msg.To = ";".join(to)
        if cc:
            msg.CC = ";".join(cc)
        if bcc:
            msg.BCC = ";".join(bcc)
        msg.Subject = subject
        msg.Body = body
        return SimpleMessage(msg, to=to, subject=subject, body=body, cc=cc, bcc=bcc)

    def send(self, message: SimpleMessage) -> str:
        message._com.Send()
        try:
            return message._com.EntryID or ""
        except Exception:
            return ""

    # -- diagnostics ------------------------------------------------------
    def counts(self) -> dict[str, int]:
        def count(folder: str) -> int:
            try:
                return int(self._folder(folder).Items.Count)
            except Exception:
                return 0

        return {"inbox": count("inbox"), "sent": count("sentitems")}

    def mailbox(self) -> str:
        try:
            user = self._ns.CurrentUser.AddressEntry.GetExchangeUser()
            smtp = getattr(user, "PrimarySmtpAddress", "") if user is not None else ""
            if smtp:
                return smtp
        except Exception:
            pass
        try:
            return self._ns.CurrentUser.Name or ""
        except Exception:
            return ""