from mailagent.output import Console, _visual_rtl, is_windows_terminal


def test_visual_rtl_changes_logical_order():
    logical = "سلام دنیا"
    visual = _visual_rtl(logical)
    assert visual != logical


def test_visual_rtl_keeps_plain_english():
    assert _visual_rtl("hello world") == "hello world"


def test_visual_rtl_preserves_newlines():
    out = _visual_rtl("سلام\nدنیا")
    assert out.count("\n") == 1


def test_console_on_forces_visual(monkeypatch):
    monkeypatch.setenv("MAILAGENT_VISUAL_RTL", "on")
    assert Console().visual_rtl is True


def test_console_off_disables_visual(monkeypatch):
    monkeypatch.setenv("MAILAGENT_VISUAL_RTL", "off")
    assert Console().visual_rtl is False


def test_console_auto_uses_windows_terminal_detection(monkeypatch):
    monkeypatch.setenv("MAILAGENT_VISUAL_RTL", "auto")
    monkeypatch.setenv("WT_SESSION", "abc")
    assert Console().visual_rtl is False
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("WT_PROFILE_ID", raising=False)
    assert Console().visual_rtl is True
    assert is_windows_terminal() is False