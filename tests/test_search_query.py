from datetime import datetime

from fakes import FakeClient, FakeItem, FakeMailbox, make_settings
from mailagent.tools import ToolBox


def _search(box, **kwargs):
    return box.search_emails(**kwargs)["items"]


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
    results = _search(box,to="bala")
    assert len(results) == 1
    assert results[0]["item_id"] == "1"
    assert "hunter2" not in results[0]["preview"]


def test_search_by_sender():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = _search(box,from_="alice")
    assert len(results) == 1
    assert results[0]["item_id"] == "1"


def test_search_by_body():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = _search(box,body_contains="hunter")
    assert len(results) == 1


def test_search_by_subject():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = _search(box,subject_contains="other")
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
    results = _search(box,to="bala", preview=True)
    assert results[0]["preview"]
    assert "hunter2" not in results[0]["preview"]


def test_preview_off_by_default():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    results = _search(box,to="bala")
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
    results = _search(box,until="2025-06-01")
    assert len(results) == 1


def test_search_subject_masked():
    item = FakeItem(
        "9",
        "password hunter2",
        FakeMailbox("A", "a@example.com"),
        [FakeMailbox("B", "b@example.com")],
    )
    box = ToolBox(settings=make_settings(), backend=FakeClient([item]))
    results = _search(box)
    assert "hunter2" not in results[0]["subject"]


def test_search_empty_result_is_explicit():
    box = ToolBox(settings=make_settings(), backend=FakeClient([]))
    result = box.search_emails()
    assert result["count"] == 0
    assert result["items"] == []
    assert "Do not invent" in result["note"]


def test_search_coerces_string_arguments():
    box = ToolBox(settings=make_settings(), backend=FakeClient(_items()))
    result = box.search_emails(limit="10", preview="True")
    assert result["count"] == 2
    assert result["items"][0]["preview"]