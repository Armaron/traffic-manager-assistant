# Traffic Manager Assistant

Local inbox for a traffic manager. The app reads work chats, analyzes them, and drafts a reply. **It never sends messages automatically.**

Phase 1 is a working skeleton: backend health check + a frontend that shows whether the backend is connected.

## What you need

Install these two programs first:

1. **Python 3.12+** — https://www.python.org/downloads/
2. **Node.js 20+** (includes `npm`) — https://nodejs.org/

On Windows you can also install Python from a terminal:

```powershell
winget install -e --id Python.Python.3.12
```

After installing Python, **close and reopen the terminal**. Then check:

```powershell
python --version
node --version
```

You should see Python `3.12` or newer, and a Node version.

If `python` opens the Microsoft Store instead of showing a version, use the full path:

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" --version
```

Then create the venv with that same path:

```powershell
cd C:\Users\arman\cas\backend
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
```

## First launch (Windows)

Open PowerShell and go to the project folder:

```powershell
cd C:\Users\arman\cas
```

### 1. Create the env file

```powershell
copy .env.example .env
```

You do not need API keys for Phase 1. Keep these values:

```
TYPEX_MODE=mock
AI_PROVIDER=mock
```

### 2. Start the backend

Open **Terminal 1**:

```powershell
cd C:\Users\arman\cas\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

If Windows blocks the venv script, run this once, then try `Activate.ps1` again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Check that the API is alive:

http://127.0.0.1:8000/health

You should see JSON with `"status": "ok"`.

### 3. Start the frontend

Open **Terminal 2**:

```powershell
cd C:\Users\arman\cas\frontend
npm install
npm run dev
```

Open:

http://127.0.0.1:5173

The page is the Inbox dashboard. Load mock chats once:

```powershell
curl.exe -X POST http://127.0.0.1:8000/dev/seed
```

Or click **Load mock chats** if the list is empty.

### 4. Run backend tests (optional)

In the backend terminal, with the venv still active:

```powershell
cd C:\Users\arman\cas\backend
pytest
```

## Project layout

```
cas/
  backend/app/          Python API
  frontend/src/         React UI
  data/                 SQLite at data/traffic_manager.db
  .env.example          Config template
```

Inbox talks to messengers through `MessengerAdapter`. TypeX, Slack, and Telegram each get their own adapter later. The UI never calls TypeX directly.

## Safety rules

- Secrets stay in `.env` only.
- API keys never go to the frontend.
- Message text is not logged in full.
- No Send button in this version. Flow is **READ → ANALYZE → DRAFT**.

## TypeX note

Real TypeX access uses **TypeX Desktop MCP** (read-only in this version). Docs: [TypeX MCP](https://docs.typex.im/).

- Enable MCP in TypeX Desktop if the installed version exposes it.
- Set `TYPEX_MCP_URL` to the endpoint from that TypeX version. The default `http://127.0.0.1:52222/mcp/` is a fallback only — verify it before `TYPEX_MODE=real`.
- Diagnose tools without message content: `python -m app.integrations.typex_discover`
- Real TypeX Sync is **limited**: chats and messages can be imported, but many records have **unknown direction**. The Inbox stores them without treating them as incoming. Confirm direction manually before drafting a reply.
- Do not execute a live TypeX DB import until you explicitly approve a controlled first sync (2 chats / 5 messages, OpenRouter off).
- Until a working MCP endpoint is verified, keep `TYPEX_MODE=mock`. Do not scrape the TypeX UI.

## Telegram (user account, read-only)

Telegram uses the **MTProto user API** (Telethon), not Bot API. The app never sends messages, never marks chats read, and never downloads media.

1. Create API credentials at [https://my.telegram.org](https://my.telegram.org) (App api_id / api_hash).
2. Copy `.env.example` → `.env` if you have not already.
3. Set:
   - `TELEGRAM_MODE=real`
   - `TELEGRAM_API_ID=`
   - `TELEGRAM_API_HASH=`
   - `TELEGRAM_SESSION_PATH=data/telegram.session`
4. From `backend/` with the venv active, authorize once (interactive phone / login code / optional 2FA):

```powershell
cd C:\Users\arman\cas\backend
.\.venv\Scripts\Activate.ps1
python -m app.integrations.telegram_auth
```

5. Start the backend, then check `GET /integrations/telegram/health`.
6. Use **Sync Telegram** in the Inbox only after you explicitly approve the first real sync. Do not leave credentials or the session file in git.

Keep `TELEGRAM_MODE=mock` for local development without Telegram credentials.

## Next step

Slack real adapter is not wired yet. TypeX Limited Sync is implemented but the first live DB import still needs explicit approval (2 chats / 5 messages, OpenRouter off).
