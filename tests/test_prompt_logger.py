import json

from llama_index.core.callbacks.schema import CBEventType

from mailagent.prompt_logger import PromptLogger


class Msg:
    def __init__(self, role, content):
        self.role = role
        self.content = content


class Resp:
    def __init__(self, content):
        self.message = Msg("assistant", content)


def test_prompt_logger_chat(tmp_path):
    path = tmp_path / "llm.jsonl"
    logger = PromptLogger(path)
    logger.on_event_end(
        CBEventType.LLM,
        {"messages": [Msg("system", "sys"), Msg("user", "hi")], "response": Resp("hello")},
        "id",
    )

    assert logger.latest is not None
    assert logger.latest["kind"] == "chat"
    assert logger.latest["messages"][1]["content"] == "hi"
    assert logger.latest["response"]["content"] == "hello"

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "chat"


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