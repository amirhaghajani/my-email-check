from datetime import datetime

from fakes import FakeClient, FakeItem, FakeMailbox, make_settings
from mailagent.tools import ToolBox


def _items():
    return [
        FakeItem(
            "1",
            "Password reset",
            FakeMailbox("Alice", "alice@example.com"),
            [FakeMailbox("Bala Bala", "bala@example.com")],
            body="my password is hunter2",
        ),
        FakeItem(
            "2",
            "Other topic",
            FakeMailbox("Bob", "bob@example.com"),
            [FakeMailbox("Carol", "carol@example.com")],
            body="nothing sensitive",
        ),
    ]


def test_search_by_recipient():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.search_emails(to="bala")
    assert len(results) == 1
    assert results[0]["item_id"] == "1"
    assert "hunter2" not in results[0]["preview"]


def test_search_by_sender():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.search_emails(from_="alice")
    assert len(results) == 1
    assert results[0]["item_id"] == "1"


def test_search_by_body():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.search_emails(body_contains="hunter")
    assert len(results) == 1


def test_search_by_subject():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.search_emails(subject_contains="other")
    assert len(results) == 1
    assert results[0]["item_id"] == "2"


def test_read_email_masks_secret():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    email = box.read_email("1")
    assert email["item_id"] == "1"
    assert "hunter2" not in email["body"]
    assert "***" in email["body"]


def test_read_email_show_secrets():
    box = ToolBox(settings=make_settings(report_show_secrets=True), backend=FakeClient(_items()))
    email = box.read_email("1")
    assert "hunter2" in email["body"]


def test_resolve_recipient():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.resolve_recipient("bala")
    assert results[0]["email"] == "bala@example.com"


def test_preview_opt_in_masks_secret():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.search_emails(to="bala", preview=True)
    assert results[0]["preview"]
    assert "hunter2" not in results[0]["preview"]


def test_preview_off_by_default():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = box.search_emails(to="bala")
    assert results[0]["preview"] == ""


def test_until_date_includes_whole_day():
    item = FakeItem(
        "3",
        "Hi",
        FakeMailbox("A", "a@example.com"),
        [FakeMailbox("B", "b@example.com")],
        sent=datetime(2025, 6, 1, 18, 0, 0),
    )
    box = ToolBox(settings=make_settings(), backend=FakeClient([item]))
    results = box.search_emails(until="2025-06-01")
    assert len(results) == 1


def test_search_subject_masked():
    item = FakeItem(
        "9",
        "password hunter2",
        FakeMailbox("A", "a@example.com"),
        [FakeMailbox("B", "b@example.com")],
    )
    box = ToolBox(settings=make_settings(), backend=FakeClient([item]))
    results = box.search_emails()
    assert "hunter2" not in results[0]["subject"]