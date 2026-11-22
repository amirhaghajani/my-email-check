"""Console encoding, secret masking, and safe report paths."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from .config import Settings

# key/value style secrets, plus common Persian phrasings
_SECRET_PATTERNS = [
    re.compile(
        r"(?i)\b(password|passwd|pwd|pass|pin|otp|token|secret|api[_-]?key)\b"
        r"\s*(?:is|:|=|\u2011|-)?\s*([^\s,;]+)"
    ),
    re.compile(
        r"(رمز\s*عبور|کلمه\s*عبور|گذرواژه|رمز)\s*(?:عبارتست|است|:|=)?\s*([^\s,;]+)"
    ),
]

_MASK = "***"
_ALLOWED_SUFFIXES = {".md", ".txt", ".log", ".csv", ".json"}


def configure_console() -> None:
    """Force UTF-8 on stdout/stderr so Persian text renders in Windows Terminal."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def is_windows_terminal() -> bool:
    """Windows Terminal sets WT_SESSION; the legacy console does not."""
    return bool(os.environ.get("WT_SESSION") or os.environ.get("WT_PROFILE_ID"))


def _visual_rtl(text: str) -> str:
    """Reorder logical text into visual order for terminals without bidi support."""
    try:
        import arabic_reshaper
    except Exception:
        return text
    try:
        try:
            from bidi import get_display
        except ImportError:  # python-bidi < 0.5
            from bidi.algorithm import get_display
    except Exception:
        return text
    try:
        return "\n".join(
            get_display(arabic_reshaper.reshape(line)) for line in text.split("\n")
        )
    except Exception:
        return text


class Console:
    """Print helper that applies bidi reordering when the terminal lacks it.

    Windows Terminal applies the Unicode bidi algorithm itself, so we leave the
    text in logical order. Legacy conhost does not, so we pre-apply visual order.
    Override with MAILAGENT_VISUAL_RTL=on|off|auto.
    """

    def __init__(self) -> None:
        mode = os.environ.get("MAILAGENT_VISUAL_RTL", "auto").lower()
        if mode == "on":
            self.visual_rtl = True
        elif mode == "off":
            self.visual_rtl = False
        else:
            self.visual_rtl = not is_windows_terminal()

    def print(self, text: str = "", end: str = "\n") -> None:
        if self.visual_rtl and text:
            text = _visual_rtl(text)
        print(text, end=end)


console = Console()


def redact(text: str, show_secrets: bool = False) -> str:
    """Mask detected secrets unless show_secrets is True."""
    if show_secrets or not text:
        return text
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(lambda m: f"{m.group(1)} {_MASK}", result)
    return result


def redact_value(value: str, show_secrets: bool = False) -> str:
    """Redact a value object (dict/list/str) for safe display to the model/user."""
    if show_secrets:
        return value
    if isinstance(value, str):
        return redact(value, show_secrets=False)
    if isinstance(value, dict):
        return {k: redact_value(v, show_secrets=False) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v, show_secrets=False) for v in value]
    return value


def safe_output_path(raw_path: str, settings: Settings) -> Path:
    """Resolve a report path confined to OUTPUT_DIR.

    Blocks path traversal and refuses hidden/sensitive files and non-report
    extensions so a broad OUTPUT_DIR cannot be used to clobber .env or source.
    """
    base = Path(settings.output_dir).expanduser().resolve()
    candidate = Path(raw_path).expanduser()
    target = candidate if candidate.is_absolute() else base / candidate
    target = target.resolve()

    if target != base and base not in target.parents:
        raise ValueError(
            f"Refusing to write outside output directory: {target} (allowed root: {base})"
        )
    if target == base:
        raise ValueError("Path must name a file, not the output directory")
    if target.name.startswith("."):
        raise ValueError(f"Refusing to write hidden/sensitive file: {target.name}")
    if target.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError(
            f"Refusing to write {target.suffix or 'extensionless'} file; "
            f"allowed: {', '.join(sorted(_ALLOWED_SUFFIXES))}"
        )
    if target.exists() and target.is_dir():
        raise ValueError(f"Refusing to overwrite a directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target