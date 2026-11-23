from fastapi.testclient import TestClient
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.llms import ChatMessage, ChatResponse, CustomLLM, LLMMetadata

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


class FakeLLM(CustomLLM):
    @property
    def metadata(self):
        return LLMMetadata(
            context_window=8192,
            num_output=256,
            is_chat_model=True,
            is_function_calling_model=True,
        )

    async def astream_chat_with_tools(self, tools, chat_history, **kwargs):
        async def _gen():
            yield ChatResponse(
                message=ChatMessage(role="assistant", content="fake response")
            )

        return _gen()

    def get_tool_calls_from_response(self, response, **kwargs):
        return []

    def chat(self, messages, **kwargs):
        return ChatResponse(message=ChatMessage(role="assistant", content="fake response"))

    def stream_chat(self, messages, **kwargs):
        yield self.chat(messages, **kwargs)

    def complete(self, prompt, **kwargs):
        return self.chat([ChatMessage(role="user", content=prompt)], **kwargs)

    def stream_complete(self, prompt, **kwargs):
        yield self.complete(prompt, **kwargs)


def test_web_chat_returns_elapsed(tmp_path):
    settings = Settings(_env_file=None, output_dir=str(tmp_path))
    agent = FunctionAgent(tools=[], llm=FakeLLM(), system_prompt="sys")
    app = create_app(settings, backend=FakeClient([]), agent=agent)
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "hi"})
    assert response.status_code == 200
    data = response.json()
    assert data["response"] == "fake response"
    assert data["elapsed_ms"] is not None
    assert data["elapsed_ms"] >= 0


def test_web_crawl_status_idle(tmp_path):
    client = TestClient(_app(tmp_path))
    data = client.get("/api/crawl/status").json()
    assert data["status"] == "idle"


def test_web_crawl_without_database(tmp_path):
    client = TestClient(_app(tmp_path))
    data = client.post("/api/crawl", json={"until": "2025-01-01"}).json()
    assert data["started"] is False
    assert "DATABASE_URL" in data["error"]


def test_web_search_without_database(tmp_path):
    client = TestClient(_app(tmp_path))
    data = client.post("/api/search", json={"q": "x"}).json()
    assert data["mode"] == "none"