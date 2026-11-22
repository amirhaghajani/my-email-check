from fakes import FakeClient, FakeItem, FakeMailbox, make_settings
from mailagent.tools import ToolBox


def _items():
    return [
        FakeItem(
            "1",
            "creds",
            FakeMailbox("A", "a@example.com"),
            [FakeMailbox("B", "b@example.com")],
            body="my password is hunter2",
        ),
        FakeItem(
            "2",
            "clean",
            FakeMailbox("A", "a@example.com"),
            [FakeMailbox("B", "b@example.com")],
            body="hello there",
        ),
    ]


def test_scan_masks_by_default(tmp_path):
    box = ToolBox(
        settings=make_settings(output_dir=str(tmp_path)),
        backend=FakeClient(_items()),
    )
    result = box.scan_emails_for_secrets(max_items=10)

    assert result["scanned"] == 2
    assert result["findings_count"] == 1
    assert result["findings"][0]["value"] == "***"
    assert "hunter2" not in result["findings"][0]["context"]


def test_scan_writes_report(tmp_path):
    box = ToolBox(
        settings=make_settings(output_dir=str(tmp_path)),
        backend=FakeClient(_items()),
    )
    result = box.scan_emails_for_secrets(max_items=10, report_path="scan.md")

    assert result["report"]
    report = (tmp_path / "scan.md").read_text(encoding="utf-8")
    assert "Secret scan" in report
    assert "hunter2" not in report