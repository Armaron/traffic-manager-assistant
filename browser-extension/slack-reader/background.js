const DEFAULT_BACKEND = "http://127.0.0.1:8000";
const TOKEN_HEADER = "X-CAS-Slack-Browser-Token";

async function settings() {
  const stored = await chrome.storage.local.get({
    backendUrl: DEFAULT_BACKEND,
    localToken: "",
    autoCapture: true,
  });
  return {
    backendUrl: String(stored.backendUrl || DEFAULT_BACKEND).replace(/\/$/, ""),
    localToken: String(stored.localToken || ""),
    autoCapture: stored.autoCapture !== false,
  };
}

async function postJson(path, body) {
  const cfg = await settings();
  if (!cfg.localToken) {
    await chrome.storage.local.set({ lastIngestError: "missing-token" });
    return { ok: false, error: "missing-token" };
  }
  try {
    const response = await fetch(cfg.backendUrl + path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [TOKEN_HEADER]: cfg.localToken,
      },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      const error = "http-" + response.status;
      await chrome.storage.local.set({ lastIngestError: error });
      return { ok: false, error };
    }
    const data = await response.json();
    await chrome.storage.local.set({ lastIngestError: "", lastIngest: data });
    return { ok: true, data };
  } catch (_err) {
    await chrome.storage.local.set({ lastIngestError: "backend-unreachable" });
    return { ok: false, error: "backend-unreachable" };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) return;
  if (message.type === "slack-browser-heartbeat") {
    postJson("/integrations/slack-browser/heartbeat", message.payload || { workspace_present: false })
      .then((result) => sendResponse(result))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (message.type === "slack-browser-events") {
    postJson("/integrations/slack-browser/events", message.payload)
      .then((result) => sendResponse(result))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
  if (message.type === "capture-active") {
    captureActiveSlackTab()
      .then((result) => sendResponse(result))
      .catch(() => sendResponse({ ok: false, error: "no-tab" }));
    return true;
  }
});

async function captureActiveSlackTab() {
  const tabs = await chrome.tabs.query({ url: "https://app.slack.com/*" });
  if (!tabs.length) {
    return { ok: false, error: "no-slack-tab" };
  }
  const active = tabs.find((tab) => tab.active) || tabs[0];
  try {
    const result = await chrome.tabs.sendMessage(active.id, { type: "capture-now" });
    return result || { ok: false, error: "no-content-script" };
  } catch (_err) {
    return { ok: false, error: "no-content-script" };
  }
}
