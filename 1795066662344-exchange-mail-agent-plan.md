# Plan: Exchange Mail Agent (CLI)

## Goal

A single-command, console-based agent that connects to the company's **on-premises Exchange Server** via EWS, lets you give instructions in plain text (Persian or English), and uses LLM-chosen MCP tools to read/search mail, draft/send mail (send gated by your confirmation), and write report files. No UI, no server.

Example it must handle:
> "Check all emails I sent to Mr Bala Bala, find passwords I sent him, and report them so I can change them."

## Decisions (confirmed with user)

| Area | Decision |
|---|---|
| Exchange | On-premises Exchange Server (EWS still supported) |
| Auth | Dedicated **service account + ApplicationImpersonation** (configurable NTLM/Basic) |
| Mailbox | **Single configured mailbox** (the operator's) |
| LLM | **OpenAI-compatible** endpoint (`base_url` + `token` + `model`) — Ollama/OpenRouter/OpenAI/any gateway |
| Framework | **LlamaIndex** (`FunctionAgent`) + **MCP-style tools** |
| Architecture | **Single-process CLI** (no FastAPI; not needed without a UI/network client) |
| MCP wiring | Tools are **real MCP tools** (FastMCP server included for reuse/testing) but the CLI agent calls them **in-process**, so `send_email` can prompt `y/n` on the console |
| Send safety | `send_email` **always asks for confirmation** unless `SEND_AUTO_APPROVE=true` |
| Persian display | **Windows Terminal** + UTF-8; rely on terminal bidi/RTL (no `python-bidi`) |
| Secret handling | Reports **mask secret values by default**; `REPORT_SHOW_SECRETS=true` to reveal |

## Architecture

```
                 Windows Terminal (UTF-8, Persian/RTL)
                          |
                 +----------------------+
                 |  CLI REPL (cli.py)   |   one command: python -m mailagent
                 |  Context (per run)   |   or one-shot: python -m mailagent "query"
                 +----------+-----------+
                            |
                 +----------v-----------+
                 |  FunctionAgent       |  LlamaIndex, OpenAI-compatible LLM
                 |  (agent.py)          |  system prompt + tool selection
                 +----------+-----------+
                            | calls in-process
     +-----------+----------+-----------+-----------+
     |           |          |           |           |
 resolve_    search_    read_      create_     send_      write_
 recipient   emails     email      email       email      text_file
     |           |          |           |           |           |
     +-----------+----------+-----------+-----------+-----------+
                            |
                 +----------v-----------+
                 |  ExchangeClient      |  exchangelib, Account(IMPERSONATION)
                 |  (exchange_client.py)|
                 +----------+-----------+
                            |
                 On-prem Exchange EWS (Exchange.asmx)

  exchange_mcp_server.py  -> FastMCP server wrapping the SAME tool functions
                             (run via: uv run mcp dev src/mailagent/exchange_mcp_server.py)
                             for external MCP clients / debugging. Not required at runtime.
```

Why in-process tools: a stdio MCP subprocess uses stdin for the protocol, so a tool cannot prompt you. In-process calls let `send_email` print the draft and block on `input()`. The FastMCP server is still delivered so the tools are genuine, reusable MCP tools.

## MCP Tool Contracts

All tools are Python functions in `tools.py`, type-hinted and documented (docstrings become the LLM schema). Shared state (EWS account, draft store, config) is injected once at startup.

1. `resolve_recipient(name: str) -> list[{name, email, type}]`
   - EWS ResolveNames. Lets the agent turn "Mr Bala Bala" into real addresses before searching.
2. `search_emails(to: str|None, from_: str|None, subject_contains: str|None, body_contains: str|None, since: str|None, until: str|None, folder: "sentitems"|"inbox"|"all", limit: int=25, has_attachments: bool|None) -> list[summary]`
   - Summary per hit: `item_id, subject, from, to, cc, datetime_sent, has_attachments`.
   - Bounded by date range (default `since` = 1 year) and `limit` to avoid huge pulls. Recipient matching may be done client-side over the date-bounded set when EWS recipient-substring search is unreliable.
3. `read_email(item_id: str, include_body: bool=True, max_body_chars: int=4000) -> {subject, from, to, cc, sent, body_text, attachments:[names]}`
   - Converts HTML body to text.
4. `create_email(to: list[str], subject: str, body: str, cc: list[str]|None=None, bcc: list[str]|None=None) -> draft_id`
   - Builds a `Message`, stores it in an in-memory draft store, returns `draft_id`. Does **not** send.
5. `send_email(draft_id: str) -> {sent: bool, message_id}`
   - Prints the draft (To/Subject/Body). Prompts `Send this email? [y/N]`. Sends only on `y` (or if `SEND_AUTO_APPROVE=true`). Calls `Message.send()`.
6. `write_text_file(path: str, content: str, append: bool=False) -> {path}`
   - Writes UTF-8. `path` is resolved relative to `OUTPUT_DIR`; traversal outside it is rejected.

## Config & Secrets (`.env`, loaded by pydantic-settings)

```
LLM_BASE_URL=http://localhost:11434/v1     # or https://openrouter.ai/api/v1
LLM_API_KEY=not-needed
LLM_MODEL=qwen2.5
EXCHANGE_SERVER=mail.company.local
EXCHANGE_USERNAME=DOMAIN\svc_mailagent
EXCHANGE_PASSWORD=...
EXCHANGE_AUTH_TYPE=NTLM                    # NTLM | BASIC
EXCHANGE_VERIFY_SSL=true                   # false for internal CA (warned)
EXCHANGE_ACCESS_TYPE=IMPERSONATION
MAILBOX_EMAIL=operator@company.local
OUTPUT_DIR=reports
REPORT_SHOW_SECRETS=false
SEND_AUTO_APPROVE=false
```

- `.env` is git-ignored; `.env.example` committed.
- Passwords/tokens never logged; errors redacted.

## Persian / Windows Console

- `output.py::configure_console()`: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` (and stderr). No `python-bidi` — Windows Terminal handles RTL; double-reordering would break it.
- Docs require `set PYTHONUTF8=1` (and recommend installing **Vazirmatn** or using Segoe UI).
- Reports written as UTF-8 Markdown in `reports/`.

## Safety & Failure Modes

- **No send without confirmation** (human-in-the-loop).
- **Secret masking** in console/report by default; opt-in reveal.
- **Path traversal** blocked for `write_text_file`.
- **EWS auth/impersonation errors** -> friendly message with remediation (RBAC scope missing, EWS URL, TLS trust).
- **Throttling/timeouts** -> bounded queries, clear error, no infinite retry.
- **Unknown recipient** -> agent reports candidates instead of guessing.
- **LLM lacks tool-calling** -> startup check; clear message naming a supported model.

## Repo Layout

```
my-email-check/
  pyproject.toml            # deps: exchangelib, llama-index-core,
                            # llama-index-llms-openai-like, mcp, pydantic-settings
  .env.example
  .gitignore                # .env, reports/, __pycache__
  README.md                 # setup, Exchange RBAC, run, examples
  src/mailagent/
    __init__.py
    __main__.py             # entry: python -m mailagent
    cli.py                  # REPL + one-shot, Context lifecycle
    config.py               # pydantic-settings
    exchange_client.py      # exchangelib Account(IMPERSONATION)
    tools.py                # 6 tool functions + draft store + redaction
    exchange_mcp_server.py  # FastMCP wrapper over tools.py
    agent.py                # OpenAILike LLM + FunctionAgent + system prompt
    output.py               # UTF-8 console, masking, report helpers
  tests/
    test_search_query.py
    test_redaction.py
    test_file_guard.py
    test_send_gate.py       # monkeypatched send, asserts y/n gate
  reports/                  # generated (gitignored)
```

## Implementation Tasks (ordered)

1. Scaffold project (`uv`/venv, `pyproject.toml`, `.gitignore`, `.env.example`, package dirs).
2. `config.py`: pydantic-settings model, `.env` load, startup validation (LLM URL/model present; Exchange fields present).
3. `exchange_client.py`: build `Credentials` + `Configuration(server, auth_type, verify_ssl)` + `Account(primary_smtp_address=MAILBOX_EMAIL, access_type=IMPERSONATION, autodiscover=False)`. Add a `ping()` (Inbox count) for self-test.
4. `output.py`: `configure_console()`, `redact(text)`, `mask_secrets(obj)`, `safe_output_path()`.
5. `tools.py`: implement the 6 tools against the shared `ExchangeClient`; draft store; `send_email` confirmation gate honoring `SEND_AUTO_APPROVE`; secret masking on tool results returned to the LLM (unless `REPORT_SHOW_SECRETS`).
6. `exchange_mcp_server.py`: FastMCP (`MCPServer`/`FastMCP`) exposing the same 6 functions for external use.
7. `agent.py`: `OpenAILike(model, api_base=LLM_BASE_URL, api_key=LLM_API_KEY, is_chat_model=True, is_function_calling_model=True)`; `FunctionAgent(tools=..., llm=..., system_prompt=...)`; system prompt instructs name resolution, Sent Items default, no fabrication, confirm before send, report in user's language.
8. `cli.py` + `__main__.py`: interactive REPL (`Context` reused across turns) and one-shot `python -m mailagent "query"`; `exit`/`quit`; graceful Ctrl+C.
9. `tests/`: unit tests with mocked EWS (no real mailbox): query construction, redaction, path guard, send gate, draft store.
10. `README.md`: prerequisites, Exchange admin RBAC steps, LLM config for Ollama/OpenRouter, run examples (including the Bala Bala scenario), Persian terminal setup.

### Exchange admin prerequisites (document in README, not code)

```powershell
New-ManagementScope -Name "MailAgentScope" -RecipientRestrictionFilter { EmailAddress -eq 'operator@company.local' }
New-ManagementRoleAssignment -Name "MailAgentImpersonation" -Role ApplicationImpersonation `
  -User "DOMAIN\svc_mailagent" -CustomRecipientWriteScope "MailAgentScope"
```

Grant EWS access as required (`Get-CASMailbox` / IIS EWS virtual directory) and ensure the service account can reach `https://<server>/EWS/Exchange.asmx`.

## Validation

- **Unit tests** (mock EWS): `uv run pytest`.
- **Self-test**: `python -m mailagent --self-test` -> prints LLM model, mailbox, Inbox/Sent item counts.
- **Manual smoke (read-only)**: `python -m mailagent "list my 5 most recent sent emails to Bala and summarize each"`.
- **End-to-end example**: `python -m mailagent "find passwords I sent to Mr Bala Bala in the last year and write a report"`.
  - Expect: resolve_recipient -> search_emails(sentitems) -> read_email on hits -> write_text_file -> masked report.
- **Send gate**: ask it to draft and send a test email; confirm it prints the draft and requires `y`.

## Out of Scope

- Web UI, FastAPI/HTTP service, multi-user mailboxes, calendar/tasks/contacts beyond ResolveNames, reading attachments' contents, changing passwords in external systems, automatic deletion/moving of mail.

## Open Risks / Notes

- EWS recipient-substring search can be unreliable; plan uses date-bounded search + client-side recipient matching.
- On-prem TLS often uses an internal CA -> `EXCHANGE_VERIFY_SSL=false` is supported but must be a deliberate, warned choice.
- The OpenAI-compatible model **must support function calling** (e.g., qwen2.5, llama3.1, gpt-4o-mini); startup should fail clearly otherwise.