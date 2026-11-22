from fastapi.testclient import TestClient

from fakes import FakeClient
from mailagent.config import Settings
from mailagent.web import create_app


def _app(tmp_path):
    settings = Settings(
        _env_file=None,
        mail_backend="ews",
        exchange_server="mail.corp",
        mailbox_email="me@corp",
        output_dir=str(tmp_path),
    )
    return create_app(settings, username="svc", password="pw", backend=FakeClient([]))


def test_web_info(tmp_path):
    client = TestClient(_app(tmp_path))
    response = client.get("/api/info")
    assert response.status_code == 200
    assert response.json()["backend"] == "ews"
    assert response.json()["model"]


def test_web_index_serves_html(tmp_path):
    client = TestClient(_app(tmp_path))
    response = client.get("/")
    assert response.status_code == 200
    assert "<html" in response.text.lower()


def test_web_prompt_and_drafts_empty(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.get("/api/prompt").json()["latest"] is None
    assert client.get("/api/drafts").json()["drafts"] == []


def test_web_reset(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.post("/api/reset").json() == {"ok": True}