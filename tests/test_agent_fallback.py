import asyncio

from mailagent.agent import parse_text_tool_call, run_with_fallback


class Msg:
    def __init__(self, content):
        self.content = content


class Resp:
    def __init__(self, content):
        self.response = Msg(content)


class FakeAgent:
    def __init__(self):
        self.calls = 0

    async def run(self, text, ctx=None, memory=None):
        self.calls += 1
        if self.calls == 1:
            return Resp('{"name": "search_emails", "parameters": {"limit": 5}}')
        return Resp("final answer")


def test_parse_text_tool_call():
    parsed = parse_text_tool_call('{"name": "search_emails", "parameters": {"limit": 5}}')
    assert parsed == ("search_emails", {"limit": 5})


def test_parse_text_tool_call_markdown_and_arguments():
    content = '```json\n{"tool": "search_emails", "arguments": "{\\"limit\\": 5}"}\n```'
    parsed = parse_text_tool_call(content)
    assert parsed == ("search_emails", {"limit": 5})


def test_parse_text_tool_call_ignores_prose():
    assert parse_text_tool_call("hello world") is None


def test_run_with_fallback_executes_text_tool_call():
    agent = FakeAgent()
    calls = []
    tool_map = {"search_emails": lambda **kw: calls.append(kw) or ["email1"]}

    content = asyncio.run(
        run_with_fallback(agent, ctx=None, memory=None, text="hi", tool_map=tool_map)
    )

    assert content == "final answer"
    assert calls == [{"limit": 5}]
    assert agent.calls == 2


class SequenceAgent:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def run(self, text, ctx=None, memory=None):
        self.calls += 1
        content = self.responses.pop(0) if self.responses else "done"
        return Resp(content)


def test_fallback_refuses_state_changing_tool():
    agent = SequenceAgent(
        [
            '{"name": "send_email", "arguments": {"to": ["x"]}}',
            '{"name": "send_email", "arguments": {"draft_id": "x"}}',
            "final answer",
        ]
    )
    calls = []
    tool_map = {"send_email": lambda **kw: calls.append(kw)}

    content = asyncio.run(run_with_fallback(agent, None, None, "hi", tool_map))

    assert calls == []
    assert content == "final answer"


def test_fallback_sanitizes_stuck_json():
    agent = SequenceAgent(
        [
            '{"name": "search_emails", "arguments": {}}',
            '{"name": "search_emails", "arguments": {}}',
            '{"name": "search_emails", "arguments": {}}',
        ]
    )
    tool_map = {"search_emails": lambda **kw: []}

    content = asyncio.run(run_with_fallback(agent, None, None, "hi", tool_map))

    assert content == "I couldn't complete that action. Please rephrase or try again."