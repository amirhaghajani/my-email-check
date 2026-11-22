"""Local web UI: Persian/RTL chat, exact LLM prompt inspector, and draft confirmation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .agent import build_agent
from .config import Settings, get_settings
from .output import configure_console, console
from .prompt_logger import PromptLogger
from .tools import ToolBox

STATIC_INDEX = Path(__file__).parent / "static" / "index.html"


class ChatRequest(BaseModel):
    message: str


def _as_text(result: object) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if content is not None:
        return str(content)
    return str(result)


def create_app(
    settings: Settings | None = None,
    username: str = "",
    password: str = "",
    backend: Any = None,
    agent: Any = None,
) -> FastAPI:
    from llama_index.core.callbacks import CallbackManager
    from llama_index.core.memory import ChatMemoryBuffer
    from llama_index.core.workflow import Context

    settings = settings or get_settings()
    logger = PromptLogger(Path(settings.output_dir) / "llm_prompts.jsonl")
    toolbox = ToolBox(
        settings=settings,
        username=username,
        password=password,
        backend=backend,
        defer_send=True,
    )
    if agent is None:
        agent = build_agent(settings, toolbox, callback_manager=CallbackManager([logger]))
    ctx = Context(agent)
    memory = ChatMemoryBuffer.from_defaults(llm=agent.llm)
    run_lock = asyncio.Lock()

    app = FastAPI(title="Exchange Mail Agent")
    app.state.settings = settings
    app.state.logger = logger
    app.state.toolbox = toolbox
    app.state.agent = agent
    app.state.ctx = ctx
    app.state.memory = memory

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_INDEX)

    @app.get("/api/info")
    def info() -> dict[str, Any]:
        return {
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "backend": settings.mail_backend,
            "mailbox": settings.mailbox_email or "(Outlook profile)",
        }

    @app.post("/api/chat")
    async def chat(req: ChatRequest) -> dict[str, Any]:
        async with run_lock:
            try:
                result = await agent.run(req.message, ctx=ctx, memory=memory)
                answer = _as_text(result)
            except Exception as exc:
                answer = f"[error] {exc}"
        return {"response": answer, "prompt": logger.latest}

    @app.get("/api/prompt")
    def get_prompt() -> dict[str, Any]:
        return {"latest": logger.latest, "history": logger.entries[-50:]}

    @app.post("/api/reset")
    def reset() -> dict[str, bool]:
        nonlocal ctx, memory
        ctx = Context(agent)
        memory = ChatMemoryBuffer.from_defaults(llm=agent.llm)
        app.state.ctx = ctx
        app.state.memory = memory
        return {"ok": True}

    @app.get("/api/drafts")
    def drafts() -> dict[str, Any]:
        return {"drafts": toolbox.draft_summaries()}

    @app.post("/api/drafts/{draft_id}/send")
    def send_draft(draft_id: str) -> dict[str, Any]:
        return toolbox.send_draft_now(draft_id)

    return app


def main(argv: list[str] | None = None) -> int:
    import argparse

    import uvicorn

    configure_console()
    from .cli import _silence_workflow_warnings

    _silence_workflow_warnings()
    parser = argparse.ArgumentParser(
        prog="mailagent-web", description="Local web UI for the Exchange Mail Agent"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    try:
        settings = get_settings()
    except Exception as exc:
        console.print(f"[error] Invalid configuration: {exc}")
        return 2

    if settings.mail_backend.lower() == "ews":
        from .cli import prompt_credentials

        try:
            username, password = prompt_credentials()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[aborted]")
            return 130
        except Exception as exc:
            console.print(f"[error] {exc}")
            return 2
    else:
        username, password = "", ""

    app = create_app(settings, username, password)
    console.print(f"Open http://{args.host}:{args.port}/ in your browser")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())