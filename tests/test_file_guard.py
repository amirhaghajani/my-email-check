import pytest

from fakes import FakeClient, make_settings
from mailagent.output import safe_output_path
from mailagent.tools import ToolBox


def test_safe_path_inside_output(tmp_path):
    settings = make_settings(output_dir=str(tmp_path))
    path = safe_output_path("report.md", settings)
    assert str(path).startswith(str(tmp_path))


def test_path_traversal_blocked(tmp_path):
    settings = make_settings(output_dir=str(tmp_path))
    with pytest.raises(ValueError):
        safe_output_path("../evil.txt", settings)


def test_write_text_file_utf8(tmp_path):
    box = ToolBox(settings=make_settings(output_dir=str(tmp_path)), backend=FakeClient([]))
    result = box.write_text_file("سلام.md", "سلام دنیا")
    assert result["bytes"] > 0
    assert (tmp_path / "سلام.md").read_text(encoding="utf-8") == "سلام دنیا"


def test_write_text_file_append(tmp_path):
    box = ToolBox(settings=make_settings(output_dir=str(tmp_path)), backend=FakeClient([]))
    box.write_text_file("log.txt", "one\n")
    box.write_text_file("log.txt", "two\n", append=True)
    assert (tmp_path / "log.txt").read_text(encoding="utf-8") == "one\ntwo\n"


def test_write_rejects_dotfile(tmp_path):
    box = ToolBox(settings=make_settings(output_dir=str(tmp_path)), backend=FakeClient([]))
    with pytest.raises(ValueError):
        box.write_text_file(".env", "secret = 1")


def test_write_rejects_disallowed_extension(tmp_path):
    box = ToolBox(settings=make_settings(output_dir=str(tmp_path)), backend=FakeClient([]))
    with pytest.raises(ValueError):
        box.write_text_file("evil.exe", "payload")