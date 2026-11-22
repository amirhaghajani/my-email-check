"""Capture the exact messages sent to the LLM and append them to a JSONL log."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from llama_index.core.callbacks.base_handler import BaseCallbackHandler
from llama_index.core.callbacks.schema import CBEventType


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _role(message: Any) -> str:
    role = getattr(message, "role", None)
    value = getattr(role, "value", role)
    return str(value or "unknown")


def _message(message: Any) -> dict[str, Any]:
    content = getattr(message, "content", None)
    if content is None:
        content = str(message)
    return {"role": _role(message), "content": content}


def _response(response: Any) -> Any:
    if response is None:
        return None
    message = getattr(response, "message", None)
    if message is not None:
        return _message(message)
    return {"role": "assistant", "content": str(response)}


class PromptLogger(BaseCallbackHandler):
    """Record every LLM call (messages + response) for inspection."""

    def __init__(self, path: Path, keep: int = 200) -> None:
        super().__init__([], [])
        self.path = path
        self.keep = keep
        self.entries: list[dict[str, Any]] = []
        self.latest: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def on_event_start(
        self,
        event_type: CBEventType,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        parent_id: str = "",
        **kwargs: Any,
    ) -> str:
        return event_id

    def on_event_end(
        self,
        event_type: CBEventType,
        payload: dict[str, Any] | None = None,
        event_id: str = "",
        **kwargs: Any,
    ) -> None:
        if event_type != CBEventType.LLM or not payload:
            return
        if payload.get("exception"):
            return

        messages = payload.get("messages")
        if messages is not None:
            entry: dict[str, Any] = {
                "ts": _now(),
                "kind": "chat",
                "messages": [_message(m) for m in messages],
                "response": _response(payload.get("response")),
            }
        else:
            entry = {
                "ts": _now(),
                "kind": "completion",
                "prompt": payload.get("formatted_prompt") or payload.get("prompt"),
                "response": payload.get("completion"),
            }
        self._record(entry)

    def _record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.latest = entry
            self.entries.append(entry)
            if len(self.entries) > self.keep:
                self.entries = self.entries[-self.keep :]
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def start_trace(self, trace_id: str | None = None) -> None:
        pass

    def end_trace(
        self,
        trace_id: str | None = None,
        trace_map: dict[str, list[str]] | None = None,
    ) -> None:
        pass