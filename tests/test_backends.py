from datetime import datetime

from mailagent import backend as backend_mod
from mailagent.config import Settings
from mailagent.outlook_backend import OutlookBackend, SimpleItem, _as_datetime, _outlook_date


class FakeUser:
    def __init__(self, smtp):
        self.PrimarySmtpAddress = smtp


class FakeAddressEntry:
    def __init__(self, smtp):
        self._user = FakeUser(smtp)

    def GetExchangeUser(self):
        return self._user


class FakeRecipient:
    def __init__(self, name, address, type_, smtp):
        self.Name = name
        self.Address = address
        self.Type = type_
        self.AddressEntry = FakeAddressEntry(smtp)


class FakeAttachment:
    def __init__(self, name):
        self.FileName = name
        self.DisplayName = name


class FakeAttachments:
    def __init__(self, items):
        self._items = items

    @property
    def Count(self):
        return len(self._items)

    def __iter__(self):
        return iter(self._items)


class FakeComItem:
    def __init__(self):
        self.EntryID = "id1"
        self.Subject = "Hello"
        self.SenderName = "Alice"
        self.SenderEmailAddress = "alice@corp.com"
        self.Recipients = [
            FakeRecipient("Bala", "/O=...", 1, "bala@corp.com"),
            FakeRecipient("Carol", "/O=...", 2, "carol@corp.com"),
        ]
        self.Attachments = FakeAttachments([FakeAttachment("a.pdf")])
        self.SentOn = datetime(2025, 6, 1, 12, 0, 0)
        self.Body = "my password is hunter2"


def test_to_item_maps_fields():
    backend = object.__new__(OutlookBackend)
    item = backend._to_item(FakeComItem(), fetch_body=True)
    assert isinstance(item, SimpleItem)
    assert item.id == "id1"
    assert item.subject == "Hello"
    assert item.sender.email_address == "alice@corp.com"
    assert [m.email_address for m in item.to_recipients] == ["bala@corp.com"]
    assert [m.email_address for m in item.cc_recipients] == ["carol@corp.com"]
    assert item.has_attachments is True
    assert item.attachments[0].name == "a.pdf"
    assert item.datetime_sent == datetime(2025, 6, 1, 12, 0, 0)
    assert "hunter2" in item.text_body


def test_as_datetime_handles_pywintypes_like():
    class D:
        year, month, day, hour, minute, second = 2025, 1, 2, 3, 4, 5

    assert _as_datetime(D()) == datetime(2025, 1, 2, 3, 4, 5)


def test_outlook_date_format():
    assert _outlook_date(datetime(2025, 1, 2, 3, 4)) == "01/02/2025 03:04"


def test_build_backend_outlook(monkeypatch):
    class FakeOutlook:
        def __init__(self):
            pass

    import mailagent.outlook_backend as ob

    monkeypatch.setattr(ob, "OutlookBackend", FakeOutlook)
    settings = Settings(_env_file=None, mail_backend="outlook")
    assert isinstance(backend_mod.build_backend(settings), FakeOutlook)


def test_build_backend_ews(monkeypatch):
    class FakeEws:
        def __init__(self, settings, username, password):
            self.args = (settings, username, password)

    import mailagent.exchange_client as ec

    monkeypatch.setattr(ec, "ExchangeClient", FakeEws)
    settings = Settings(
        _env_file=None,
        mail_backend="ews",
        exchange_server="mail.corp",
        mailbox_email="me@corp",
    )
    built = backend_mod.build_backend(settings, "svc", "pw")
    assert isinstance(built, FakeEws)
    assert built.args[1:] == ("svc", "pw")


def test_require_exchange_ews_needs_server():
    settings = Settings(_env_file=None, mail_backend="ews", mailbox_email="me@corp")
    try:
        settings.require_exchange()
    except ValueError:
        return
    raise AssertionError("expected ValueError for EWS without server/url")


def test_require_exchange_outlook_needs_nothing():
    settings = Settings(_env_file=None, mail_backend="outlook")
    settings.require_exchange()  # should not raise