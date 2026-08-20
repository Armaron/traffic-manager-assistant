# Slack Windows Notification Listener

Experimental fallback for Traffic Manager Assistant. It reads **Slack Desktop** toasts through the official Windows `UserNotificationListener` API and posts normalized text to the local backend.

It does **not**:

- install a Slack App
- use Slack OAuth or Slack user/app tokens
- read Slack cookies, session files, or Electron storage
- click Slack, mark messages read, or dismiss Windows notifications
- capture Chrome/Edge Slack Web notifications in V1

## Limits

- Only notifications Windows actually shows
- Muted chats and DND may hide messages
- Toast text can be truncated
- No Slack history, almost no outgoing messages
- No real Slack channel IDs or thread reconstruction
- Slack Desktop identity can differ between Store and classic installs

## Backend

In `.env`:

```
SLACK_NOTIFICATION_CAPTURE_ENABLED=true
```

Leave `SLACK_MODE` as `mock` or `real` — this capture path is independent.

Start the backend. It writes a **local application token** to `data/slack_notification_token`. This is not a Slack credential.

## Build the helper

Requires [.NET 8 SDK](https://dotnet.microsoft.com/download) and Windows 10 1809+ (17763).

```powershell
cd C:\Users\armar\cas\windows-notification-listener\TrafficManager.NotificationListener
dotnet build -c Release
```

`dotnet run` starts the UI, but Windows usually **denies** `UserNotificationListener` until the app has package identity.

## Local package identity (required for permission)

1. Enable **Developer Mode**: Settings → Privacy & security → For developers → Developer Mode.
2. From the repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows-notification-listener\register-dev.ps1
```

The script builds the helper, writes logos, copies a layout folder, and runs `Add-AppxPackage -Register`. Administrator is not required.

3. Launch **Traffic Manager Notification Listener** from the Start menu.
4. Paste the token from `data/slack_notification_token` if it is not auto-filled.
5. Click **Разрешить доступ** and accept the Windows prompt.
6. Keep Slack Desktop running with notifications enabled.

If access stays denied: Settings → System → Notifications → Traffic Manager Notification Listener.

To unregister later:

```powershell
Get-AppxPackage TrafficManager.NotificationListener | Remove-AppxPackage
```

This only removes the local Windows package. It does not change the Slack workspace.

## Discovery mode

Enable **Discovery mode** in the helper to see:

- application display name
- PackageFamilyName / AppUserModelId
- toast kind
- number of text elements

It does not show message text. If Slack Desktop is not recognized, copy the source id into `.env`:

```
SLACK_NOTIFICATION_SOURCE_IDS=your.package.family.name
```

## Inbox status

- **Slack Notifications · Connected** — helper heartbeats are arriving
- **Windows permission required**
- **Listener not running**
- **Slack notifications not detected**

This is not “Slack API connected”.
