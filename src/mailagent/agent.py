"""Build the LlamaIndex FunctionAgent and its OpenAI-compatible LLM."""

from __future__ import annotations

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai_like import OpenAILike

from .config import Settings
from .tools import ToolBox, build_tools

SYSTEM_PROMPT = """You are an assistant that operates a company mailbox through tools.

Available tools:
- resolve_recipient(name): resolve a person or partial address to concrete email addresses. Do this first when the user names someone (e.g. "Mr Bala Bala").
- search_emails(to, from_, subject_contains, body_contains, since, until, folder, limit, has_attachments, preview): search mail. folder is "sentitems" (default), "inbox", or "all". Dates are ISO strings like "2025-01-01". Set preview=true to include a short body snippet.
- read_email(item_id, include_body, max_body_chars): read one email by its item_id.
- create_email(to, subject, body, cc, bcc): create a draft (does NOT send). Returns draft_id.
- send_email(draft_id): send a draft. It always asks the user to confirm on the console.
- write_text_file(path, content, append): write a UTF-8 report under the reports directory.

Rules:
1. Never invent data. If a tool fails or returns nothing, say so plainly.
2. Resolve names to real addresses before searching.
3. For "find passwords/secrets" requests: search, read the candidate emails, then report which emails contained secrets and which accounts need a password change. Secret values are masked by default.
4. Before sending any email, create a draft and let the user confirm. Do not call send_email unless the user asked to send.
5. When asked for a report, or when a written summary is useful, write a Markdown file with write_text_file and tell the user its path.
6. Reply in the same language as the user (Persian or English).
"""


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
        system_prompt=SYSTEM_PROMPT,
        verbose=False,
    )