from typing import ClassVar

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.llms import ChatMessage, ChatResponse, CustomLLM, LLMMetadata
from llama_index.core.workflow import Context


class EchoLLM(CustomLLM):
    calls: ClassVar[list[list[str]]] = []

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=32768,
            num_output=512,
            is_chat_model=True,
            is_function_calling_model=True,
        )

    async def astream_chat_with_tools(self, tools, chat_history, **kwargs):
        EchoLLM.calls.append([m.content for m in chat_history])

        async def _gen():
            yield ChatResponse(
                message=ChatMessage(role="assistant", content=f"n={len(chat_history)}")
            )

        return _gen()

    def get_tool_calls_from_response(self, response, **kwargs):
        return []

    def chat(self, messages, **kwargs):
        return ChatResponse(
            message=ChatMessage(role="assistant", content=f"n={len(messages)}")
        )

    def stream_chat(self, messages, **kwargs):
        yield self.chat(messages, **kwargs)

    def complete(self, prompt, **kwargs):
        return self.chat([ChatMessage(role="user", content=prompt)], **kwargs)

    def stream_complete(self, prompt, **kwargs):
        yield self.complete(prompt, **kwargs)


def test_context_preserves_history():
    import asyncio

    from llama_index.core.memory import ChatMemoryBuffer

    EchoLLM.calls.clear()
    agent = FunctionAgent(tools=[], llm=EchoLLM(), system_prompt="sys")
    ctx = Context(agent)
    memory = ChatMemoryBuffer.from_defaults(llm=agent.llm)

    async def run():
        await agent.run("first question", ctx=ctx, memory=memory)
        await agent.run("second question", ctx=ctx, memory=memory)

    asyncio.run(run())

    assert len(EchoLLM.calls) == 2
    first = EchoLLM.calls[0]
    second = EchoLLM.calls[1]

    assert "first question" in first
    # Second call must include the first exchange (memory is preserved).
    assert "first question" in second
    assert "second question" in second