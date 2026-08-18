# Slack setup (read-only)

Traffic Manager Assistant can **read** Slack conversations that the authorized user can already see. It does **not** send messages, add reactions, upload files, or change channels.

Tokens stay in the local `.env` file only. Never paste them into chat, screenshots, logs, or git.

If the workspace requires app approval, a workspace owner or admin must approve the app. Do not try to bypass that policy.

## What you will create

1. A Slack **User OAuth Token** (`xoxp-…`) for Web API reads
2. A Slack **App-Level Token** (`xapp-…`) for Socket Mode only

Do not use the app-level token for `auth.test` or conversation reads. Do not use the user token to open Socket Mode.

## Scopes (user token)

Request only these **User Token Scopes**:

- `channels:read`
- `channels:history`
- `groups:read`
- `groups:history`
- `im:read`
- `im:history`
- `mpim:read`
- `mpim:history`
- `users:read`
- `files:read`

Do **not** add:

- `chat:write`
- `files:write`
- `reactions:write`
- `channels:write`
- `groups:write`
- `im:write`
- `mpim:write`

The app-level token needs only `connections:write`.

## Step by step

1. Open [https://api.slack.com/apps](https://api.slack.com/apps) and create an app **From scratch**. Choose **internal** distribution for your workspace.
2. Select the correct workspace.
3. **OAuth & Permissions** → User Token Scopes → add the read scopes listed above. No write scopes.
4. **Socket Mode** → Enable Socket Mode.
5. **Basic Information** → App-Level Tokens → Generate Token with `connections:write` only. Store it as `SLACK_APP_TOKEN` in local `.env`.
6. **Event Subscriptions** → Enable Events. Turn on **Socket Mode** delivery (no public Request URL).
7. Subscribe to **User events** (not bot-only):
   - `message.channels`
   - `message.groups`
   - `message.im`
   - `message.mpim`
8. **Install App** (or Reinstall) to the workspace. If the workspace requires approval, ask an owner/admin. Wait until the install succeeds.
9. Copy the **User OAuth Token** into local `.env` as `SLACK_USER_TOKEN`. Never commit it.
10. In `.env` set:
    ```
    SLACK_MODE=real
    SLACK_USER_TOKEN=
    SLACK_APP_TOKEN=
    SLACK_SYNC_CHAT_LIMIT=10
    SLACK_SYNC_MESSAGE_LIMIT=20
    SLACK_DOWNLOAD_FILES=true
    ```
11. Restart the backend.
12. Open Traffic Manager Assistant and check Slack health. **Sync Slack** runs a limited recent-history reconciliation. New messages then arrive through Socket Mode.

## How it works

- Limited Web API reconciliation on startup (when Auto Sync is on) and when you click **Sync Slack**.
- Real-time messages via Socket Mode. The app ACKs the Socket envelope (protocol only) and then stores the message locally.
- Slack files are downloaded with the user token and stored under `data/attachments`. The frontend only sees local `/file` and `/thumbnail` URLs.
- AI is never triggered automatically by Slack sync.
- No Slack message can be sent from this application.

## Auto Sync

When Auto Sync is **on**: TypeX and Telegram keep their 30-second scheduler; Slack event persistence is enabled.

When Auto Sync is **off**: TypeX/Telegram automatic cycles pause. The Slack Socket connection may stay up and envelopes are still ACKed, but events are not saved. **Sync Slack** still works. Turning Auto Sync back **on** runs one limited Slack reconciliation to catch anything missed.

## If health is not ready

- `Slack setup required` — tokens missing or `SLACK_MODE` is not `real`.
- `Slack app approval required` — the workspace has not installed/approved the app. Ask an admin. Do not work around this.
