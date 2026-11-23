"""Crawl the mailbox into PostgreSQL with embeddings."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from . import db as db_module
from .config import Settings
from .exchange_client import item_id

EmbedFn = Callable[[list[str]], list[list[float] | None]]


@dataclass
class CrawlState:
    running: bool = False
    status: str = "idle"
    folder: str = ""
    until_date: str | None = None
    processed: int = 0
    last_subject: str | None = None
    last_sent_at: str | None = None
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


def _mailbox_strings(mailboxes: Any) -> list[str]:
    out: list[str] = []
    for m in mailboxes or []:
        name = getattr(m, "name", None)
        email = getattr(m, "email_address", None)
        if name and email:
            out.append(f"{name} <{email}>")
        elif email:
            out.append(email)
        elif name:
            out.append(name)
    return out


class Crawler:
    def __init__(
        self,
        settings: Settings,
        client: Any,
        embed_fn: EmbedFn | None = None,
        db_module: Any = db_module,
    ) -> None:
        self.settings = settings
        self.client = client
        self.embed_fn = embed_fn or self._default_embed
        self.db = db_module
        self.state = CrawlState()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _default_embed(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(
            base_url=self.settings.llm_base_url,
            api_key=self.settings.llm_api_key,
        )
        response = client.embeddings.create(
            model=self.settings.embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def start(self, until_date: str, folder: str = "all") -> bool:
        if self.state.running:
            return False
        self._stop.clear()
        self.state = CrawlState(
            running=True,
            status="running",
            folder=folder,
            until_date=until_date,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._thread = threading.Thread(
            target=self._run, args=(until_date, folder), daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        return asdict(self.state)

    def _run(self, until_date: str, folder: str) -> None:
        conn = None
        run_id = None
        try:
            self.settings.require_database()
            conn = self.db.connect(self.settings)
            self.db.init_db(conn)
            run_id = self.db.start_crawl_run(
                conn, date.fromisoformat(until_date), folder
            )
            for name in self._folders(folder):
                if self._stop.is_set():
                    break
                self._crawl_folder(conn, name, until_date)
            final_status = "stopped" if self._stop.is_set() else "completed"
        except Exception as exc:
            self.state.error = str(exc)
            final_status = "error"
        finally:
            self.state.status = final_status
            self.state.running = False
            self.state.finished_at = datetime.now(timezone.utc).isoformat()

            if conn is not None and run_id is not None:
                try:
                    self.db.update_crawl_run(
                        conn, run_id, self.state.processed, final_status, self.state.error
                    )
                    conn.commit()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _folders(self, folder: str) -> list[str]:
        name = (folder or "all").lower()
        if name == "all":
            return ["sentitems", "inbox"]
        return [name]

    def _crawl_folder(self, conn: Any, folder: str, until_date: str) -> None:
        until_dt = datetime.fromisoformat(until_date)
        if until_dt.tzinfo is None:
            until_dt = until_dt.replace(tzinfo=timezone.utc)

        last = self.db.get_last_sent_at(conn, folder)
        batch: list[dict[str, Any]] = []

        for item in self.client.iter_items(
            folder=folder,
            since=until_dt,
            until=last,
            batch_size=50,
            max_items=None,
            fetch_body=True,
        ):
            if self._stop.is_set():
                break
            self.state.processed += 1
            self.state.last_subject = getattr(item, "subject", "") or ""
            sent = getattr(item, "datetime_sent", None)
            self.state.last_sent_at = sent.isoformat() if sent else None
            batch.append(self._to_row(item, folder))
            if len(batch) >= 25:
                self._flush(conn, batch)
                batch = []

        if batch:
            self._flush(conn, batch)

    def _to_row(self, item: Any, folder: str) -> dict[str, Any]:
        sender = getattr(item, "sender", None)
        sender_name = getattr(sender, "name", "") or ""
        sender_email = getattr(sender, "email_address", "") or ""
        sent = getattr(item, "datetime_sent", None)
        return {
            "id": item_id(item),
            "folder": folder,
            "subject": getattr(item, "subject", "") or "",
            "sender_name": sender_name,
            "sender_email": sender_email,
            "to_recipients": _mailbox_strings(getattr(item, "to_recipients", None)),
            "cc_recipients": _mailbox_strings(getattr(item, "cc_recipients", None)),
            "sent_at": sent,
            "body_text": (getattr(item, "text_body", None) or "")[:20000],
            "has_attachments": bool(getattr(item, "has_attachments", False)),
        }

    def _flush(self, conn: Any, rows: list[dict[str, Any]]) -> None:
        self.db.upsert_emails(conn, rows)

        texts = [f"{r['subject']}\n{r['body_text']}"[:8000] for r in rows]
        try:
            vectors = self.embed_fn(texts)
        except Exception:
            vectors = [None] * len(rows)

        embeddings = []
        for row, vector in zip(rows, vectors):
            if vector is not None:
                embeddings.append(
                    {
                        "email_id": row["id"],
                        "embedding": vector,
                        "model": self.settings.embedding_model,
                    }
                )
        if embeddings:
            self.db.upsert_embeddings(conn, embeddings)

        conn.commit()