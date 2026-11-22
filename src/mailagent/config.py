"""Application configuration loaded from a local .env file.

Exchange credentials are NOT stored here. They are requested interactively at
startup (hidden password input) and passed directly to the Exchange client.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_project_env() -> Path | None:
    """Locate the project .env by walking up from this file to pyproject.toml."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent / ".env"
    return None


_PROJECT_ENV = _find_project_env()
# CWD .env wins; otherwise fall back to the project-root .env so the app works
# no matter which directory it is launched from.
_ENV_FILES: tuple[str, ...] = tuple(
    p for p in ((_PROJECT_ENV and str(_PROJECT_ENV)), ".env") if p
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # LLM (OpenAI-compatible)
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "not-needed"
    llm_model: str = "qwen2.5"
    # context window of the chosen model (for token budgeting)
    llm_context_window: int = 32768

    # Mail backend: "ews" (service account + impersonation) or "outlook"
    # (uses the installed, already-configured Outlook profile / MAPI).
    mail_backend: str = Field(default="ews", pattern="^(ews|outlook)$")

    # Exchange / EWS
    exchange_server: str = ""
    exchange_ews_url: str = ""           # full EWS URL, e.g. https://mail.corp/EWS/Exchange.asmx
    exchange_autodiscover: bool = False  # use EWS autodiscover instead of a fixed server
    exchange_auth_type: str = Field(default="NTLM", pattern="^(NTLM|BASIC|GSSAPI)$")
    exchange_verify_ssl: bool = True
    exchange_access_type: str = Field(default="IMPERSONATION", pattern="^(IMPERSONATION|DELEGATE)$")
    mailbox_email: str = ""

    # Behaviour
    output_dir: str = "reports"
    report_show_secrets: bool = False
    send_auto_approve: bool = False

    def require_llm(self) -> None:
        if not self.llm_base_url or not self.llm_model:
            raise ValueError("LLM_BASE_URL and LLM_MODEL must be set")

    def require_exchange(self) -> None:
        # The Outlook backend uses the local Outlook profile and needs no config.
        if self.mail_backend.lower() == "outlook":
            return
        if not (self.exchange_ews_url or self.exchange_server):
            raise ValueError(
                "Missing required Exchange settings: EXCHANGE_SERVER or EXCHANGE_EWS_URL"
            )
        if not self.mailbox_email:
            raise ValueError("Missing required Exchange settings: MAILBOX_EMAIL")


def get_settings() -> Settings:
    return Settings()