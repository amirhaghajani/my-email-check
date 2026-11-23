# Exchange Mail Agent

A console (CLI) agent that connects to an **on-premises Microsoft Exchange Server** via EWS,
lets you give instructions in plain text (Persian or English), and uses an LLM to choose and
run tools: search mail, read mail, draft mail, send mail (with your confirmation), and write
report files. No web UI, no server process.

Example:

```
you> Check all emails I sent to Mr Bala Bala, find the passwords I sent him,
     and write a report of which accounts I must change.
agent> I resolved "Mr Bala Bala" to bala@example.com, searched Sent Items,
        read 4 matching emails, and wrote reports/bala-passwords.md.
        Accounts to change: ...
```

## Requirements

- Python 3.11+ (3.12/3.13 recommended)
- For `MAIL_BACKEND=ews`: network access to the EWS endpoint
  (`https://<server>/EWS/Exchange.asmx`) and a **service account** with `ApplicationImpersonation`
  on the target mailbox (Exchange admin setup below)
- For `MAIL_BACKEND=outlook`: Microsoft Outlook installed with a configured profile (Windows)
- An **OpenAI-compatible LLM endpoint** whose model supports function/tool calling
  (Ollama, OpenRouter, OpenAI, an internal gateway, ...)

## Install

```powershell
cd C:\p\my-email-check
uv sync --extra dev
copy .env.example .env
```

## Exchange admin setup (EWS backend, one time)

Run in the Exchange Management Shell (replace names):

```powershell
New-ManagementScope -Name "MailAgentScope" -RecipientRestrictionFilter { EmailAddress -eq 'operator@company.local' }

New-ManagementRoleAssignment -Name "MailAgentImpersonation" -Role ApplicationImpersonation `
  -User "DOMAIN\svc_mailagent" -CustomRecipientWriteScope "MailAgentScope"
```

Make sure the service account can reach the EWS virtual directory and is allowed to use EWS
(`Get-CASMailbox <service account>` / IIS EWS settings). If your Exchange uses an internal CA,
set `EXCHANGE_VERIFY_SSL=false` (a warning is printed at startup).

## Mail backends

Two backends are supported (`MAIL_BACKEND` in `.env`):

- **`ews` (default)** — on-premises Exchange Web Services via `exchangelib`, using a service
  account with `ApplicationImpersonation`. Works unattended. Point it at EWS with one of:
  - `EXCHANGE_SERVER=mail.company.local` (host; the app appends `/EWS/Exchange.asmx`)
  - `EXCHANGE_EWS_URL=https://mail.company.local/EWS/Exchange.asmx` (full URL)
  - `EXCHANGE_AUTODISCOVER=true` (discover the EWS endpoint)
- **`outlook`** — uses the locally installed, already-configured Outlook profile (which speaks
  MAPI/HTTP or RPC/HTTP) through COM. No Exchange password is needed, but it is desktop-only,
  runs as the current Windows user, and cannot impersonate a service account. Requires Outlook
  installed with a configured profile.

Outlook using MAPI/HTTP does **not** disable EWS; the two coexist. Prefer `ews` for unattended
service-account use, and `outlook` when you want to reuse the Outlook profile with no password.

## Configure

Non-secret settings live in `.env` (copied from `.env.example`). With `MAIL_BACKEND=ews` the app
prompts for credentials interactively; with `MAIL_BACKEND=outlook` it uses the local Outlook
profile and asks nothing.

```powershell
copy .env.example .env
notepad .env
```

With `MAIL_BACKEND=ews`, at startup it asks:

```text
Exchange username (DOMAIN\user or UPN):
Exchange password:
```

The password uses hidden input (`getpass`): it is not on the command line, not in shell
history, not in the process environment, and not echoed. It requires a real console (a TTY);
the app refuses to run if stdin is piped. With `MAIL_BACKEND=outlook`, no prompt appears.

`SEND_AUTO_APPROVE=false` means `send_email` always asks you to confirm. `REPORT_SHOW_SECRETS=true`
reveals detected secret values in the console and reports (default is masked).

## Run

```powershell
# connectivity check (LLM + Exchange)
uv run python -m mailagent --self-test

# interactive REPL
uv run python -m mailagent

# one-shot
uv run python -m mailagent "list my 5 most recent sent emails to Bala and summarize them"

# print the exact LLM prompt (messages + response) after each answer
uv run python -m mailagent --show-prompt
```

In the REPL, type `exit` or press Ctrl+C to quit.

## Web UI (recommended for Persian)

A local web page handles Persian/RTL input and output correctly and shows the exact LLM prompt.

```powershell
uv run mailagent-web
# or
uv run python -m mailagent.web

# then open http://127.0.0.1:8765/
```

Options: `--host 127.0.0.1 --port 8765`.

The page has:
- A chat box (Persian/English, RTL).
- A live **«در حال پردازش... Ns»** waiting indicator (with elapsed seconds) while the agent runs,
  and the total time shown under each answer.
- A **Prompt LLM** tab showing the exact messages + response sent to the LLM (including tool calls
  and per-call `duration_ms`).
- A **Drafts** tab: in the web UI, `send_email` does **not** send; it creates a draft and you
  click **Send**. This is the confirmation step.
- Prompts are also appended to `reports/llm_prompts.jsonl`.

## Crawl to PostgreSQL + semantic search

The web UI's **Crawl** tab copies mail into a local PostgreSQL database with embeddings.

1. Add to `.env`:
   ```ini
   DATABASE_URL=postgresql://user:pass@localhost:5432/mailagent
   EMBEDDING_MODEL=nomic-embed-text   # or text-embedding-3-small, etc.
   ```
2. Make sure the embedding model exists on the LLM provider (e.g. `ollama pull nomic-embed-text`).
   The `pgvector` extension is created automatically.
3. In the web UI, open **Crawl**, pick a date and folder, and click **Start crawl**:
   - Crawls newest → selected date, in batches of 50.
   - Saves fields (subject, sender, recipients, date, body) + an embedding.
   - **Resumable** — restarting continues from the last `sent_at`.
   - **Stop** stops after the current item.
4. Use the **Search** tab for semantic search (pgvector `<=>`), with a SQL `ILIKE` fallback if
   embeddings are unavailable.

Schema (auto-created): `emails`, `email_embeddings`, `crawl_runs`.

## Persian / Windows console

- **Use Windows Terminal** — it applies the Unicode bidi algorithm, so Persian renders right-to-left.
- In the **legacy console** (the old PowerShell/CMD window), Persian appears left-to-right. The app
  auto-detects this and pre-orders text visually (`python-bidi` + `arabic-reshaper`). Override with
  `MAILAGENT_VISUAL_RTL=on` (force) or `off` (disable).
- The app forces UTF-8 on stdout/stderr. Set `PYTHONUTF8=1` for extra safety.
- Use a Persian-capable font (e.g. **Vazirmatn**, or Segoe UI). In the legacy console, set a
  TrueType font via the title bar → Properties → Font; the default raster font cannot show Persian.
- Reports are written as UTF-8 Markdown under `reports/` and render correctly in editors.

## Tools the agent can use

| Tool | Purpose |
|---|---|
| `resolve_recipient(name)` | Resolve a person/partial address to concrete mailboxes |
| `search_emails(...)` | Search Sent Items / Inbox / all; filter by to, from, subject, body, dates, attachments |
| `scan_emails_for_secrets(...)` | Batch-scan mail with local detectors for passwords/secrets (use for "check all my emails") |
| `read_email(item_id)` | Read one email's headers and body text |
| `create_email(...)` | Create a draft (does **not** send) |
| `send_email(draft_id)` | Send a draft — **always asks for confirmation** |
| `write_text_file(path, content)` | Write a UTF-8 report under `OUTPUT_DIR` |

## Bulk secret scan ("check all my emails")

`search_emails` is capped at 200 per call and has no pagination, so it is **not** a bulk audit.
For "find all passwords/secrets I sent" requests, the agent uses `scan_emails_for_secrets`:

- Pages through the mailbox **server-side** in batches (default 50).
- Runs local detectors: `password=`, `passwd:`, `user:pass`, URL credentials, connection
  strings, private keys, and Persian «رمز عبور».
- Masks values by default; writes a Markdown report under `OUTPUT_DIR`.
- Scans up to `max_items` (default 1000).

Example:
```text
you> Scan my whole Sent Items for passwords or secrets and write a report.
```

One-shot:
```powershell
uv run python -m mailagent "scan sent items for secrets, up to 5000 emails, report to scan.md"
```

Professionals combine this deterministic pass with an LLM triage of only the candidate snippets
(batched, with a strict JSON schema), then aggregate/deduplicate into a final report.

## Optional: run the tools as an MCP server

The same tools are also exposed as a real MCP server for external MCP clients or debugging:

```powershell
uv run mcp dev src/mailagent/exchange_mcp_server.py
# or
uv run python -m mailagent.exchange_mcp_server
```

With `MAIL_BACKEND=ews`, MCP mode has no interactive terminal, so it reads `EXCHANGE_USERNAME`
and `EXCHANGE_PASSWORD` from environment variables. With `MAIL_BACKEND=outlook`, no credentials
are needed. Set `SEND_AUTO_APPROVE=true` there too (its stdin is the protocol channel, so it
cannot prompt a human). The CLI itself uses the tools **in-process** so `send_email` can prompt you.

## Tests

```powershell
uv run pytest -q
```

Unit tests use mocked EWS/Outlook objects (no real mailbox): search filtering, secret masking,
path-traversal guard, UTF-8 report writing, the send confirmation gate, and backend selection.

## Security notes

- Secrets are masked in console output and reports unless `REPORT_SHOW_SECRETS=true`.
- With `MAIL_BACKEND=ews`, Exchange credentials are entered interactively with hidden input
  (`getpass`) and are never stored in `.env`, environment variables, or the repo. The only
  exception is the optional MCP server (no terminal), which reads them from environment variables.
  With `MAIL_BACKEND=outlook`, no Exchange password is used; the local Outlook profile is used.
- Do **not** pass credentials as command-line arguments: command lines are visible in Task Manager
  and `Get-CimInstance Win32_Process`.
- `write_text_file` cannot escape `OUTPUT_DIR`, cannot overwrite dotfiles, and only writes
  `.md/.txt/.log/.csv/.json` files. Keep `OUTPUT_DIR` dedicated to reports.
- Email sending is always gated by a human confirmation unless you explicitly enable auto-approve.

## Troubleshooting

- **`.env` changes not picked up** — the app loads the project-root `.env` (found via
  `pyproject.toml`) regardless of the directory you launch it from. Confirm it is at
  `C:\p\my-email-check\.env`.
- **`Invalid configuration: exchange_auth_type ...`** — `EXCHANGE_AUTH_TYPE` must be one of
  `NTLM`, `BASIC`, or `GSSAPI` (not `NEGO`). Use `NTLM` for a service account with a password.
- **EWS connection fails** — set `EXCHANGE_EWS_URL` to the full
  `https://<server>/EWS/Exchange.asmx`, or `EXCHANGE_AUTODISCOVER=true`. Outlook using
  MAPI/HTTP does **not** mean EWS is disabled; they coexist.
- **Outlook backend fails** — Outlook must be installed with a configured profile, and the app
  must run in an interactive Windows session (COM automation).
- **401 / impersonation errors** — check the RBAC scope/assignment, the username you entered at
  the prompt (`DOMAIN\user` or UPN), and `EXCHANGE_ACCESS_TYPE`.
- **TLS errors** — internal CA; set `EXCHANGE_VERIFY_SSL=false` (deliberate, warned).
- **LLM "model does not support tools"** — pick a tool-calling model and set
  `LLM_MODEL` / `LLM_BASE_URL` correctly; run `--self-test`.
- **Agent forgets earlier messages** — the agent keeps a persistent `ChatMemoryBuffer` per
  session. Click **گفتگوی جدید / New chat** (or restart) to reset. The
  `UnserializableKeyWarning` about `memory` is expected and is suppressed.
- **Agent invents emails or dates** — the system prompt now includes today's date and forbids
  inventing data. Empty searches return `{"count": 0, "items": [], "note": "No emails matched..."}`.
  If it still happens, use a stronger tool-calling model.
- **Model outputs a tool call as JSON text** — some models (e.g. `llama3.1:8b`) don't use native
  function calling reliably. The app parses text tool calls and executes **read-only** tools
  (`search_emails`, `read_email`, `resolve_recipient`, `scan_emails_for_secrets`) for up to 2
  retries, and coerces string args like `"10"` / `"True"`. State-changing tools (`send_email`,
  `create_email`, `write_text_file`) are **never** executed this way; leftover raw JSON is replaced
  with a friendly message. For best results, use a model with native tool calling (`qwen3:14b`,
  `qwen2.5:14b`, `mistral-nemo`, `gpt-4o-mini`).
- **Persian text looks wrong** — use Windows Terminal with a Persian-capable font and `PYTHONUTF8=1`.