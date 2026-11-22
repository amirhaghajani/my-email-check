"""Command-line entry point: interactive REPL, one-shot query, or self-test.

Exchange credentials are requested interactively at startup with hidden input.
They are never read from .env or environment variables.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sys
import warnings
from pathlib import Path

from llama_index.core.callbacks import CallbackManager
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.workflow import Context

from .agent import build_agent, build_llm
from .backend import build_backend
from .config import Settings, get_settings
from .output import configure_console, console, is_windows_terminal
from .prompt_logger import PromptLogger
from .tools import ToolBox

BANNER = "Exchange Mail Agent - type a request, or 'exit' to quit."


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


async def _ask(agent, ctx: Context, text: str, memory: ChatMemoryBuffer) -> str:
    result = await agent.run(text, ctx=ctx, memory=memory)
    return _as_text(result)


def prompt_credentials() -> tuple[str, str]:
    """Prompt for the Exchange username and password (hidden input)."""
    if not sys.stdin.isatty():
        raise RuntimeError(
            "Exchange credentials must be entered in an interactive console "
            "(stdin is not a TTY)."
        )
    username = input("Exchange username (DOMAIN\\user or UPN): ").strip()
    if not username:
        raise ValueError("Exchange username is required")
    password = getpass.getpass("Exchange password: ")
    if not password:
        raise ValueError("Exchange password is required")
    return username, password


def _print_prompt(logger: PromptLogger) -> None:
    if logger.latest is None:
        return
    console.print("\n--- LLM prompt (latest) ---")
    console.print(json.dumps(logger.latest, ensure_ascii=False, indent=2))
    console.print("--- end prompt ---\n")


async def repl(
    settings: Settings,
    username: str,
    password: str,
    logger: PromptLogger,
    show_prompt: bool = False,
) -> int:
    toolbox = ToolBox(settings=settings, username=username, password=password)
    agent = build_agent(settings, toolbox, callback_manager=CallbackManager([logger]))
    ctx = Context(agent)
    memory = ChatMemoryBuffer.from_defaults(llm=agent.llm)

    console.print(BANNER)
    while True:
        try:
            text = input("you> ")
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        stripped = text.strip()
        if stripped.lower() in ("exit", "quit", ":q"):
            return 0
        if not stripped:
            continue
        try:
            answer = await _ask(agent, ctx, text, memory)
            console.print("\nagent> " + answer + "\n")
            if show_prompt:
                _print_prompt(logger)
        except KeyboardInterrupt:
            console.print("\n[interrupted]")
        except Exception as exc:  # keep the REPL alive
            console.print(f"[error] {exc}\n")


async def one_shot(
    settings: Settings,
    username: str,
    password: str,
    text: str,
    logger: PromptLogger,
    show_prompt: bool = False,
) -> int:
    toolbox = ToolBox(settings=settings, username=username, password=password)
    agent = build_agent(settings, toolbox, callback_manager=CallbackManager([logger]))
    ctx = Context(agent)
    memory = ChatMemoryBuffer.from_defaults(llm=agent.llm)
    console.print(await _ask(agent, ctx, text, memory))
    if show_prompt:
        _print_prompt(logger)
    return 0


async def self_test(
    settings: Settings,
    username: str,
    password: str,
    logger: PromptLogger,
) -> int:
    ok = True
    console.print("mailagent self-test")
    console.print(f"  LLM model       : {settings.llm_model}")
    console.print(f"  LLM base url    : {settings.llm_base_url}")
    console.print(f"  Backend         : {settings.mail_backend}")
    if settings.mail_backend.lower() == "ews":
        if settings.exchange_ews_url:
            console.print(f"  EWS URL         : {settings.exchange_ews_url}")
        elif settings.exchange_autodiscover:
            console.print("  EWS             : autodiscover")
        else:
            console.print(f"  EWS server      : {settings.exchange_server or '(not set)'}")
    console.print(f"  Mailbox         : {settings.mailbox_email or '(current Outlook profile)'}")
    console.print(f"  Access type     : {settings.exchange_access_type}")
    console.print(f"  Auth type       : {settings.exchange_auth_type}")
    console.print(f"  Verify SSL      : {settings.exchange_verify_ssl}")
    console.print(f"  Terminal        : {'Windows Terminal' if is_windows_terminal() else 'legacy console'}")
    console.print(f"  Visual RTL      : {console.visual_rtl}")

    try:
        llm = build_llm(settings, callback_manager=CallbackManager([logger]))
        resp = llm.complete("Reply with the single word: ok")
        console.print(f"  LLM             : OK ({resp.text.strip()[:40]!r})")
    except Exception as exc:
        ok = False
        console.print(f"  LLM             : FAILED ({exc})")

    try:
        client = build_backend(settings, username, password)
        counts = client.counts()
        console.print(f"  Exchange        : OK mailbox={client.mailbox()} counts={counts}")
    except Exception as exc:
        ok = False
        console.print(f"  Exchange        : FAILED ({exc})")

    return 0 if ok else 1


def _warnings(settings: Settings) -> None:
    if settings.mail_backend.lower() == "outlook":
        console.print("[info] Outlook backend: using the local Outlook profile (MAPI).")
        if settings.send_auto_approve:
            console.print("[warning] SEND_AUTO_APPROVE is true: send_email will NOT ask for confirmation.")
        return
    if not settings.exchange_verify_ssl:
        console.print("[warning] EXCHANGE_VERIFY_SSL is false: TLS certificates are not validated.")
    if settings.send_auto_approve:
        console.print("[warning] SEND_AUTO_APPROVE is true: send_email will NOT ask for confirmation.")


def _silence_workflow_warnings() -> None:
    """Hide the benign 'memory is unserializable' warning from LlamaIndex Workflows."""
    try:
        from workflows.context.state_store import UnserializableKeyWarning

        warnings.filterwarnings("ignore", category=UnserializableKeyWarning)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    configure_console()
    _silence_workflow_warnings()
    parser = argparse.ArgumentParser(prog="mailagent", description=BANNER)
    parser.add_argument("query", nargs="*", help="run a single request and exit")
    parser.add_argument("--self-test", action="store_true", help="check LLM + Exchange connectivity")
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="print the exact LLM prompt (messages + response) after each answer",
    )
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except Exception as exc:
        console.print(f"[error] Invalid configuration: {exc}")
        return 2
    _warnings(settings)

    logger = PromptLogger(Path(settings.output_dir) / "llm_prompts.jsonl")

    if settings.mail_backend.lower() == "outlook":
        # Outlook uses the already-configured local profile; no password.
        username, password = "", ""
    else:
        try:
            username, password = prompt_credentials()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[aborted]")
            return 130
        except Exception as exc:
            console.print(f"[error] {exc}")
            return 2

    try:
        if args.self_test:
            return asyncio.run(self_test(settings, username, password, logger))
        if args.query:
            return asyncio.run(
                one_shot(
                    settings,
                    username,
                    password,
                    " ".join(args.query),
                    logger,
                    args.show_prompt,
                )
            )
        return asyncio.run(repl(settings, username, password, logger, args.show_prompt))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())