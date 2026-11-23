"""Local web UI: Persian/RTL chat, exact LLM prompt inspector, and draft confirmation."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db
from .agent import build_agent, run_with_fallback
from .config import Settings, get_settings
from .crawler import Crawler
from .output import configure_console, console
from .prompt_logger import PromptLogger
from .tools import ToolBox

STATIC_INDEX = Path(__file__).parent / "static" / "index.html"


class ChatRequest(BaseModel):
    message: str


class CrawlRequest(BaseModel):
    until: str
    folder: str = "all"


class SearchRequest(BaseModel):
    q: str
    limit: int = 10


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

    crawler = Crawler(settings, toolbox.backend)
    app.state.crawler = crawler

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
        import time

        started = time.perf_counter()
        async with run_lock:
            try:
                answer = await run_with_fallback(
                    agent, ctx, memory, req.message, toolbox.tool_map()
                )
            except Exception as exc:
                answer = f"[error] {exc}"
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {"response": answer, "prompt": logger.latest, "elapsed_ms": elapsed_ms}

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

    @app.post("/api/crawl")
    def start_crawl(req: CrawlRequest) -> dict[str, Any]:
        try:
            date.fromisoformat(req.until)
        except ValueError:
            return {"started": False, "error": "until must be YYYY-MM-DD"}
        if not settings.database_url:
            return {"started": False, "error": "DATABASE_URL is not set"}
        started = crawler.start(req.until, req.folder)
        if not started:
            return {"started": False, "error": "a crawl is already running"}
        return {"started": True}

    @app.get("/api/crawl/status")
    def crawl_status() -> dict[str, Any]:
        return crawler.status()

    @app.post("/api/crawl/stop")
    def stop_crawl() -> dict[str, bool]:
        crawler.stop()
        return {"stopping": True}

    @app.post("/api/search")
    def search(req: SearchRequest) -> dict[str, Any]:
        if not settings.database_url:
            return {"error": "DATABASE_URL is not set", "results": [], "mode": "none"}
        try:
            conn = db.connect(settings)
        except Exception as exc:
            return {"error": str(exc), "results": [], "mode": "none"}

        try:
            embedding = None
            try:
                vectors = crawler.embed_fn([req.q])
                embedding = vectors[0] if vectors else None
            except Exception:
                embedding = None

            rows = db.search(conn, req.q, embedding, max(1, min(req.limit, 50)))
            return {
                "results": rows,
                "mode": "vector" if embedding is not None else "sql",
            }
        except Exception as exc:
            return {"error": str(exc), "results": [], "mode": "error"}
        finally:
            conn.close()

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

    if not settings.database_url:
        console.print("[warning] DATABASE_URL is not set; crawling/search are disabled.")

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