from datetime import datetime

from mailagent.config import Settings


class FakeMailbox:
    def __init__(self, name: str, email: str):
        self.name = name
        self.email_address = email


class FakeItem:
    def __init__(
        self,
        id,
        subject,
        sender,
        to,
        cc=None,
        sent=None,
        has_attachments=False,
        body="",
    ):
        self.id = id
        self.subject = subject
        self.sender = sender
        self.to_recipients = to
        self.cc_recipients = cc or []
        self.datetime_sent = sent or datetime(2025, 6, 1, 12, 0, 0)
        self.has_attachments = has_attachments
        self.text_body = body
        self.attachments = []


class FakeAccount:
    default_timezone = None


class FakeMessage:
    def __init__(self, to, subject, body, cc=None, bcc=None):
        self.to_recipients = [FakeMailbox(a, a) for a in to]
        self.cc_recipients = [FakeMailbox(a, a) for a in (cc or [])]
        self.bcc_recipients = [FakeMailbox(a, a) for a in (bcc or [])]
        self.subject = subject
        self.text_body = body


class FakeClient:
    def __init__(self, items):
        self.account = FakeAccount()
        self.items = items
        self.sent = []

    def search(self, folder="sentitems", since=None, until=None, subject_contains=None, limit=25, fetch_body=False):
        out = []
        for item in self.items:
            if since and item.datetime_sent < since:
                continue
            if until and item.datetime_sent > until:
                continue
            if subject_contains and subject_contains.lower() not in (item.subject or "").lower():
                continue
            out.append(item)
        return out[:limit]

    def get_item(self, item_id):
        for item in self.items:
            if item.id == item_id:
                return item
        raise KeyError(item_id)

    def iter_items(
        self,
        folder="sentitems",
        since=None,
        until=None,
        subject_contains=None,
        batch_size=50,
        max_items=None,
        fetch_body=True,
    ):
        limit = max_items if max_items is not None else len(self.items)
        for item in self.search(
            folder=folder,
            since=since,
            until=until,
            subject_contains=subject_contains,
            limit=limit,
            fetch_body=fetch_body,
        ):
            yield item

    def resolve_names(self, name):
        return [FakeMailbox("Bala Bala", "bala@example.com")]

    def create_message(self, to, subject, body, cc=None, bcc=None):
        return FakeMessage(to, subject, body, cc, bcc)

    def send(self, message):
        self.sent.append(message)
        return "new-id"


def make_settings(**overrides):
    base = dict(
        report_show_secrets=False,
        send_auto_approve=False,
        output_dir="reports",
    )
    base.update(overrides)
    # Isolate tests from any real .env in the project.
    return Settings(_env_file=None, **base)