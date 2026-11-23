"""Build the LlamaIndex FunctionAgent and its OpenAI-compatible LLM."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai_like import OpenAILike

from .config import Settings
from .tools import ToolBox, build_tools

SYSTEM_PROMPT = """You are an assistant that operates a company mailbox through tools.

Available tools:
- resolve_recipient(name): resolve a person or partial address to concrete email addresses. Do this first when the user names someone (e.g. "Mr Bala Bala").
- search_emails(to, from_, subject_contains, body_contains, since, until, folder, limit, has_attachments, preview): search mail. folder is "sentitems" (default), "inbox", or "all". Dates are ISO strings like "2025-01-01". Set preview=true to include a short body snippet.
- scan_emails_for_secrets(folder, since, until, max_items, batch_size, report_path): scan mail in batches with local detectors for passwords/secrets. Use this for "check all my emails" requests instead of reading emails one by one.
- read_email(item_id, include_body, max_body_chars): read one email by its item_id.
- create_email(to, subject, body, cc, bcc): create a draft (does NOT send). Returns draft_id.
- send_email(draft_id): send a draft. It always asks the user to confirm on the console.
- write_text_file(path, content, append): write a UTF-8 report under the reports directory.

Rules:
1. Never invent data. If a tool fails, returns an empty list, or returns count: 0, say plainly that nothing was found. Do not generate example emails, names, dates, or placeholders.
2. Resolve names to real addresses before searching.
3. For "find passwords/secrets" requests: search, read the candidate emails, then report which emails contained secrets and which accounts need a password change. Secret values are masked by default.
4. Before sending any email, create a draft and let the user confirm. Do not call send_email unless the user asked to send.
5. When asked for a report, or when a written summary is useful, write a Markdown file with write_text_file and tell the user its path.
6. Reply in the same language as the user (Persian or English).
7. For bulk "find all passwords/secrets" requests, use scan_emails_for_secrets (batched, local detection) and then write a report. Do not try to read every email individually.
8. Before answering, verify every email, recipient, subject, and date you mention came from a tool result. If you cannot cite an item_id, do not mention it.
"""


def _system_prompt() -> str:
    today = datetime.now().strftime("%Y-%m-%d (%A)")
    return (
        SYSTEM_PROMPT
        + f"\n\nToday's date is {today}. Use it for 'today', 'last N days', "
        "and relative dates."
    )


def build_llm(settings: Settings, callback_manager=None) -> OpenAILike:
    settings.require_llm()
    return OpenAILike(
        model=settings.llm_model,
        api_base=settings.llm_base_url,
        api_key=settings.llm_api_key,
        context_window=settings.llm_context_window,
        is_chat_model=True,
        is_function_calling_model=True,
        temperature=0.1,
        callback_manager=callback_manager,
    )


def build_agent(settings: Settings, toolbox: ToolBox, callback_manager=None) -> FunctionAgent:
    llm = build_llm(settings, callback_manager=callback_manager)
    tools = build_tools(toolbox)
    return FunctionAgent(
        tools=tools,
        llm=llm,
        system_prompt=_system_prompt(),
        verbose=False,
    )


def _as_text(result: object) -> str:
    response = getattr(result, "response", None)
    if response is not None:
        content = getattr(response, "content", None)
        if content is not None:
            return content
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if content is not None:
        return str(content)
    return str(result)


def parse_text_tool_call(content: str) -> tuple[str, dict[str, Any]] | None:
    """Parse a tool call that the model emitted as JSON text instead of natively."""
    if not content:
        return None

    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    if start == -1:
        return None
    snippet = text[start:]

    candidates = [snippet]
    end = snippet.rfind("}")
    if end != -1:
        candidates.append(snippet[: end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        name = data.get("name") or data.get("tool") or data.get("tool_name")
        params = data.get("parameters") or data.get("arguments") or data.get("args") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except Exception:
                continue
        if isinstance(name, str) and isinstance(params, dict):
            return name, params
    return None


_FALLBACK_SAFE_TOOLS = {
    "resolve_recipient",
    "search_emails",
    "scan_emails_for_secrets",
    "read_email",
}


async def run_with_fallback(
    agent,
    ctx,
    memory,
    text: str,
    tool_map: dict[str, Any],
    max_fallbacks: int = 2,
) -> str:
    """Run the agent, and if it emits a read-only tool call as text, execute it and re-run.

    State-changing tools (send_email, create_email, write_text_file) are never
    executed from a text tool call; the model must use the native tool path so
    the normal confirmation/safety applies.
    """
    result = await agent.run(text, ctx=ctx, memory=memory)
    content = _as_text(result)

    for _ in range(max_fallbacks):
        parsed = parse_text_tool_call(content)
        if not parsed:
            break
        name, args = parsed

        if name not in _FALLBACK_SAFE_TOOLS:
            followup = (
                f"Tool {name} was not executed because it is not allowed via text. "
                "Answer the user in natural language now. Do not output JSON or tool calls."
            )
            result = await agent.run(followup, ctx=ctx, memory=memory)
            content = _as_text(result)
            continue

        fn = tool_map.get(name)
        if fn is None:
            break
        try:
            output = fn(**args)
        except Exception as exc:
            output = f"Tool error: {exc}"
        followup = (
            f"Tool {name} returned:\n{output}\n\n"
            "Use this result to answer the user in natural language. "
            "Do not output JSON or tool calls."
        )
        result = await agent.run(followup, ctx=ctx, memory=memory)
        content = _as_text(result)

    # If the model is still emitting a raw tool call, don't show it to the user.
    if parse_text_tool_call(content):
        content = "I couldn't complete that action. Please rephrase or try again."

    return content