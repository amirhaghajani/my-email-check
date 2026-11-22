import getpass

from mailagent.cli import prompt_credentials


def test_prompt_credentials_returns_hidden(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "DOMAIN\\user")
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "secret")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)

    username, password = prompt_credentials()

    assert username == "DOMAIN\\user"
    assert password == "secret"


def test_prompt_credentials_refuses_without_tty(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    try:
        prompt_credentials()
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError without a TTY")


def test_prompt_credentials_rejects_empty_username(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "  ")
    monkeypatch.setattr(getpass, "getpass", lambda prompt="": "secret")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    try:
        prompt_credentials()
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty username")