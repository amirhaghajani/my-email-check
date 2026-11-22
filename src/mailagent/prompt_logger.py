"""Capture the exact messages sent to the LLM and append them to a JSONL log."""

from __future__ import annotations

import json
import threading
import time
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


def _tool_calls(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in raw or []:
        if isinstance(call, dict):
            out.append(call)
            continue
        fn = getattr(call, "function", None)
        out.append(
            {
                "id": getattr(call, "id", ""),
                "type": getattr(call, "type", "function"),
                "function": {
                    "name": getattr(fn, "name", ""),
                    "arguments": getattr(fn, "arguments", ""),
                },
            }
        )
    return out


def _message(message: Any) -> dict[str, Any]:
    content = getattr(message, "content", None)
    if content is None:
        content = ""
    data: dict[str, Any] = {"role": _role(message), "content": content}

    additional = getattr(message, "additional_kwargs", None) or {}
    if additional.get("tool_calls"):
        data["tool_calls"] = _tool_calls(additional["tool_calls"])
    if additional.get("function_call"):
        data["function_call"] = additional["function_call"]
    return data


def _response(response: Any) -> Any:
    if response is None:
        return None
    message = getattr(response, "message", None)
    if message is not None:
        return _message(message)
    return {"role": "assistant", "content": str(response)}


class PromptLogger(BaseCallbackHandler):
    """Record every LLM call (messages, response, tool calls, duration)."""

    def __init__(self, path: Path, keep: int = 200) -> None:
        super().__init__([], [])
        self.path = path
        self.keep = keep
        self.entries: list[dict[str, Any]] = []
        self.latest: dict[str, Any] | None = None
        self._starts: dict[str, float] = {}
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
        if event_type == CBEventType.LLM and event_id:
            with self._lock:
                self._starts[event_id] = time.monotonic()
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

        with self._lock:
            started = self._starts.pop(event_id, None)
        duration_ms = int((time.monotonic() - started) * 1000) if started else None

        messages = payload.get("messages")
        if messages is not None:
            entry: dict[str, Any] = {
                "ts": _now(),
                "kind": "chat",
                "duration_ms": duration_ms,
                "messages": [_message(m) for m in messages],
                "response": _response(payload.get("response")),
            }
        else:
            entry = {
                "ts": _now(),
                "kind": "completion",
                "duration_ms": duration_ms,
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