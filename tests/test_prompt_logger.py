import json
import time

from llama_index.core.callbacks.schema import CBEventType

from mailagent.prompt_logger import PromptLogger


class Msg:
    def __init__(self, role, content, additional_kwargs=None):
        self.role = role
        self.content = content
        self.additional_kwargs = additional_kwargs or {}


class Resp:
    def __init__(self, content):
        self.message = Msg("assistant", content)


class FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = FakeFunction(name, arguments)


def test_prompt_logger_chat(tmp_path):
    path = tmp_path / "llm.jsonl"
    logger = PromptLogger(path)
    logger.on_event_start(CBEventType.LLM, {}, "id")
    time.sleep(0.01)
    logger.on_event_end(
        CBEventType.LLM,
        {"messages": [Msg("system", "sys"), Msg("user", "hi")], "response": Resp("hello")},
        "id",
    )

    assert logger.latest is not None
    assert logger.latest["kind"] == "chat"
    assert logger.latest["messages"][1]["content"] == "hi"
    assert logger.latest["response"]["content"] == "hello"
    assert logger.latest["duration_ms"] is not None
    assert logger.latest["duration_ms"] >= 0

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "chat"


def test_prompt_logger_captures_tool_calls(tmp_path):
    logger = PromptLogger(tmp_path / "llm.jsonl")
    message = Msg(
        "assistant",
        "",
        {"tool_calls": [FakeToolCall("1", "search_emails", "{}")]},
    )
    logger.on_event_end(
        CBEventType.LLM,
        {"messages": [message], "response": Resp("")},
        "id",
    )

    assert logger.latest is not None
    assert logger.latest["messages"][0]["tool_calls"][0]["function"]["name"] == "search_emails"


def test_prompt_logger_completion(tmp_path):
    logger = PromptLogger(tmp_path / "llm.jsonl")
    logger.on_event_end(
        CBEventType.LLM,
        {"formatted_prompt": "hello", "completion": "world"},
        "id",
    )

    assert logger.latest is not None
    assert logger.latest["kind"] == "completion"
    assert logger.latest["prompt"] == "hello"
    assert logger.latest["response"] == "world"


def test_prompt_logger_ignores_exceptions(tmp_path):
    logger = PromptLogger(tmp_path / "llm.jsonl")
    logger.on_event_end(CBEventType.LLM, {"exception": ValueError("x")}, "id")
    assert logger.latest is None