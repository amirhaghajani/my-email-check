from fakes import FakeClient, make_settings
from mailagent.tools import ToolBox


def test_send_declined_does_not_send():
    client = FakeClient([])
    box = ToolBox(settings=make_settings(), backend=client, confirm=lambda summary: False)
    draft_id = box.create_email(to=["bala@example.com"], subject="hi", body="hello")
    result = box.send_email(draft_id)
    assert result["sent"] is False
    assert client.sent == []


def test_send_confirmed_sends():
    client = FakeClient([])
    box = ToolBox(settings=make_settings(), backend=client, confirm=lambda summary: True)
    draft_id = box.create_email(to=["bala@example.com"], subject="hi", body="hello")
    result = box.send_email(draft_id)
    assert result["sent"] is True
    assert len(client.sent) == 1


def test_send_unknown_draft():
    box = ToolBox(settings=make_settings(), backend=FakeClient([]), confirm=lambda summary: True)
    result = box.send_email("missing")
    assert result["sent"] is False


def test_declined_draft_can_be_sent_later():
    client = FakeClient([])
    answers = iter([False, True])
    box = ToolBox(settings=make_settings(), backend=client, confirm=lambda summary: next(answers))
    draft_id = box.create_email(to=["bala@example.com"], subject="hi", body="hello")

    first = box.send_email(draft_id)
    assert first["sent"] is False
    assert client.sent == []

    second = box.send_email(draft_id)
    assert second["sent"] is True
    assert len(client.sent) == 1


def test_create_email_requires_recipient():
    box = ToolBox(settings=make_settings(), backend=FakeClient([]))
    try:
        box.create_email(to=[], subject="x", body="y")
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty recipients")