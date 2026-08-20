# Slack Browser Reader (local, no Slack App)

This is an alternative Slack source for Traffic Manager Assistant. It reads **only the Slack Web UI that is already open and rendered** in Chrome or Edge.

It does **not** require:

- a Slack App
- OAuth
- `xoxp` / `xapp` tokens
- installing anything in the Slack workspace

It is not Socket Mode. If the Slack tab is closed, sleeping, or logged out, the Inbox will not receive new Slack messages.

Official `SLACK_MODE=real` (Slack SDK + Socket Mode) is unchanged. Use one mode at a time.

## What the extension does

- Runs only on `https://app.slack.com/*`
- Observes visible message DOM with `MutationObserver`
- Sends normalized message text to `http://127.0.0.1:8000`
- Does not send data to a third-party server
- Does not read browser cookies
- Does not read Slack auth tokens or `localStorage` credentials
- Does not click Slack UI, scroll history, or open hidden chats
- Does not call OpenRouter; AI stays a user action in the Inbox

## Backend

1. Copy `.env.example` to `.env` if needed.
2. Set:

```
SLACK_MODE=browser
```

Leave `SLACK_USER_TOKEN` and `SLACK_APP_TOKEN` empty.

3. Start the backend. On first browser-mode start it writes a **local application token** to `data/slack_browser_token`. This is not a Slack credential. Do not commit it.
4. Optional: copy that value into `.env` as `SLACK_BROWSER_LOCAL_TOKEN`.

## Load the unpacked extension

Build step: none. Load the folder as-is.

### Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked**
4. Select `C:\Users\armar\cas\browser-extension\slack-reader`

### Edge

1. Open `edge://extensions`
2. Enable **Developer mode**
3. **Load unpacked**
4. Select `C:\Users\armar\cas\browser-extension\slack-reader`

## Connect the extension

1. Click the extension icon.
2. Paste the local token from `data/slack_browser_token`.
3. Keep backend URL `http://127.0.0.1:8000`.
4. Leave **Auto capture** on to ingest newly rendered messages.
5. Open Slack Web, open a conversation, then **Capture current conversation** for currently loaded messages.

No automatic scrolling or backfill. Only what Slack has already rendered is read.

After updating the extension, click **Reload** on `chrome://extensions` and refresh the Slack tab. Version **0.1.2** ignores date separators (`Today`, `Thursday, February 19th`) and strips sender/time chrome from the message body.

## Inbox status

- **Slack Browser · Connected** — Slack tab is open and heartbeats are arriving
- **Open Slack Web to sync** — no live Slack tab / heartbeat expired

## Limits (V1)

- Text first. Visible files/images become `[Image]` / `[File]` placeholders, not private Slack downloads
- Thread replies only if the thread pane is already open
- Off-screen virtualized messages are not treated as deleted
- Edits of a still-rendered message update the same Inbox row
