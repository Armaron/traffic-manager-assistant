const statusEl = document.getElementById("status");
const autoEl = document.getElementById("auto-capture");
const captureEl = document.getElementById("capture");
const backendEl = document.getElementById("backend-url");
const tokenEl = document.getElementById("local-token");

function setStatus(text) {
  statusEl.textContent = text;
}

function formatCapture(result, ingestError) {
  if (ingestError === "missing-token") {
    return "Paste the local token from data/slack_browser_token";
  }
  if (ingestError === "backend-unreachable" || ingestError === "http-401") {
    return ingestError === "http-401"
      ? "Backend rejected the local token"
      : "Backend not reachable at 127.0.0.1:8000";
  }
  if (!result) {
    return "Slack tab open · waiting for capture";
  }
  if (result.error === "no-messages" || result.found === 0) {
    return "Slack tab open · 0 messages in DOM. Open a conversation, then Capture";
  }
  if (result.sent > 0) {
    return "Sent " + result.sent + " of " + result.found + " visible messages";
  }
  if (result.found > 0) {
    return "Found " + result.found + " messages · click Capture";
  }
  return "Slack tab open · waiting for capture";
}

async function load() {
  const stored = await chrome.storage.local.get({
    backendUrl: "http://127.0.0.1:8000",
    localToken: "",
    autoCapture: true,
    lastCapture: null,
    lastIngestError: "",
  });
  backendEl.value = stored.backendUrl;
  tokenEl.value = stored.localToken;
  autoEl.checked = stored.autoCapture !== false;
  const tabs = await chrome.tabs.query({ url: "https://app.slack.com/*" });
  if (!tabs.length) {
    setStatus("Open Slack Web to sync");
    return;
  }
  const active = tabs.find((tab) => tab.active) || tabs[0];
  try {
    const ping = await chrome.tabs.sendMessage(active.id, { type: "ping-tab" });
    setStatus(formatCapture(ping || stored.lastCapture, stored.lastIngestError));
  } catch (_err) {
    setStatus("Reload the extension, then refresh the Slack tab");
  }
}

async function saveField() {
  await chrome.storage.local.set({
    backendUrl: backendEl.value.trim() || "http://127.0.0.1:8000",
    localToken: tokenEl.value.trim(),
    autoCapture: autoEl.checked,
  });
}

autoEl.addEventListener("change", saveField);
backendEl.addEventListener("change", saveField);
tokenEl.addEventListener("change", saveField);

captureEl.addEventListener("click", async () => {
  await saveField();
  const result = await chrome.runtime.sendMessage({ type: "capture-active" });
  const stored = await chrome.storage.local.get({ lastIngestError: "" });
  if (result && result.error === "no-slack-tab") {
    setStatus("Open Slack Web to sync");
    return;
  }
  if (result && result.error === "no-content-script") {
    setStatus("Reload the extension, then refresh the Slack tab");
    return;
  }
  setStatus(formatCapture(result, stored.lastIngestError));
});

load();
