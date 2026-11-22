"""Local, deterministic detectors for passwords/secrets in email text."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "password",
        re.compile(
            r"(?i)\b(password|passwd|pwd|pass)\b\s*(?:is|:|=|\u2011|-)?\s*([^\s,;]{3,})"
        ),
    ),
    (
        "password_fa",
        re.compile(
            r"(?:رمز\s*عبور|کلمه\s*عبور|گذرواژه)\s*(?:عبارتست|است|:|=)?\s*([^\s,;]{3,})"
        ),
    ),
    (
        "api_key",
        re.compile(
            r"(?i)\b(api[_-]?key|access[_-]?token|secret|token)\b\s*[:=]\s*([^\s,;]{6,})"
        ),
    ),
    (
        "url_credentials",
        re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://([^/\s:@]+):([^/\s@]+)@"),
    ),
    (
        "connection_string",
        re.compile(r"(?i)(?:password|pwd)\s*=\s*([^;\s]{4,})"),
    ),
    (
        "private_key",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    ),
]

_PLACEHOLDERS = {
    "password",
    "passwd",
    "pwd",
    "pass",
    "example",
    "changeme",
    "secret",
    "token",
    "***",
    "xxx",
    "...",
}


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return lowered in _PLACEHOLDERS or lowered.startswith("***")


def _context(text: str, start: int, end: int, width: int = 80) -> str:
    left = max(0, start - width)
    right = min(len(text), end + width)
    snippet = text[left:right].replace("\n", " ").replace("\r", " ")
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def scan_text(text: str) -> list[dict[str, Any]]:
    """Return candidate secrets found in ``text`` (value + context)."""
    if not text:
        return []

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            if kind == "url_credentials":
                value = f"{match.group(1)}:{match.group(2)}"
            elif kind == "private_key":
                value = match.group(0)
            else:
                value = match.group(match.lastindex) if match.lastindex else match.group(0)

            value = value.strip()
            if not value or _is_placeholder(value):
                continue

            key = (kind, value)
            if key in seen:
                continue
            seen.add(key)

            findings.append(
                {
                    "type": kind,
                    "value": value,
                    "context": _context(text, match.start(), match.end()),
                }
            )

    return findings