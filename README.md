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

Real TypeX access is **Phase 8**. Official options from [TypeX docs](https://docs.typex.im/):

- **TypeX Desktop MCP** (preferred for this app): enable MCP in TypeX Desktop. Local endpoint is `http://127.0.0.1:52222/mcp/`. This can read the signed-in user's chats.
- **TypeX Bot API**: a bot only sees chats it is added to. That is not enough for a personal work inbox.

Until that is wired, keep `TYPEX_MODE=mock`. Do not use browser scraping.

## Next step

**Phase 5:** Mock AI analysis for selected messages.
