const statusEl = document.getElementById("status");
const autoEl = document.getElementById("auto-capture");
const captureEl = document.getElementById("capture");
const backendEl = document.getElementById("backend-url");
const tokenEl = document.getElementById("local-token");
const convEl = document.getElementById("conv-detected");
const visibleEl = document.getElementById("visible-count");
const parsedEl = document.getElementById("parsed-count");
const diagnosticsToggle = document.getElementById("parser-diagnostics");
const diagnosticsEl = document.getElementById("diagnostics");
const sanitizeEl = document.getElementById("sanitize");

function setStatus(text) {
  statusEl.textContent = text;
}

function yesNo(value) {
  return value ? "yes" : "no";
}

function applySummary(diag) {
  if (!diag) {
    convEl.textContent = "—";
    visibleEl.textContent = "—";
    parsedEl.textContent = "—";
    diagnosticsEl.hidden = true;
    return;
  }
  convEl.textContent = yesNo(Boolean(diag.conversationDetected || diag.conversation));
  visibleEl.textContent = String(diag.canonical != null ? diag.canonical : diag.found || 0);
  parsedEl.textContent = String(diag.parsed != null ? diag.parsed : diag.found || 0);
  if (diagnosticsToggle.checked) {
    diagnosticsEl.hidden = false;
    var lines = [
      "Conversation ID: " + (diag.conversation || "none"),
      "Candidates found: " + (diag.candidates || 0),
      "Canonical roots: " + (diag.canonical || 0),
      "Parsed: " + (diag.parsed != null ? diag.parsed : diag.found || 0),
      "Skipped low confidence: " + (diag.skipped || 0),
      "Stable ts: " + (diag.stable_ts || 0),
      "Fallback ids: " + (diag.fallback_ids || 0),
      "Inherited sender: " + (diag.inherited_sender || 0),
      "Unknown direction: " + (diag.unknown_direction || 0),
      "Missing sender: " + (diag.missing_sender || 0),
    ];
    (diag.items || []).forEach(function (item, index) {
      lines.push("");
      lines.push("#" + (index + 1));
      lines.push("stable_ts: " + (item.stable_ts ? "yes" : "no"));
      lines.push("sender: " + (item.sender || "missing"));
      lines.push("sender_id_present: " + Boolean(item.sender_id_present));
      lines.push("body_selector: " + (item.body_selector || "none"));
      lines.push("direction: " + (item.direction || "unknown"));
      lines.push("confidence: " + (item.confidence || "low"));
    });
    diagnosticsEl.textContent = lines.join("\n");
  } else {
    diagnosticsEl.hidden = true;
    diagnosticsEl.textContent = "";
  }
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
    return "Open Slack Web to sync";
  }
  if (result.error === "no-messages" || result.found === 0) {
    return "Connected · 0 clean messages in the current pane";
  }
  if (result.sent > 0) {
    return "Connected · sent " + result.sent + " · parsed " + (result.parsed || result.found);
  }
  if (result.found > 0) {
    return "Connected · parsed " + result.found + " clean messages";
  }
  return "Connected";
}

async function activeSlackTab() {
  const tabs = await chrome.tabs.query({ url: "https://app.slack.com/*" });
  if (!tabs.length) return null;
  return tabs.find((tab) => tab.active) || tabs[0];
}

async function load() {
  const stored = await chrome.storage.local.get({
    backendUrl: "http://127.0.0.1:8000",
    localToken: "",
    autoCapture: true,
    parserDiagnostics: false,
    lastCapture: null,
    lastIngestError: "",
  });
  backendEl.value = stored.backendUrl;
  tokenEl.value = stored.localToken;
  autoEl.checked = stored.autoCapture !== false;
  diagnosticsToggle.checked = stored.parserDiagnostics === true;
  sanitizeEl.hidden = !diagnosticsToggle.checked;
  const tab = await activeSlackTab();
  if (!tab) {
    setStatus("Open Slack Web to sync");
    applySummary(stored.lastCapture);
    return;
  }
  try {
    const ping = await chrome.tabs.sendMessage(tab.id, { type: "ping-tab" });
    const diag = (ping && ping.diagnostics) || ping || stored.lastCapture;
    setStatus(formatCapture(diag, stored.lastIngestError));
    applySummary(diag);
  } catch (_err) {
    setStatus("Reload the extension, then refresh the Slack tab");
    applySummary(stored.lastCapture);
  }
}

async function saveField() {
  await chrome.storage.local.set({
    backendUrl: backendEl.value.trim() || "http://127.0.0.1:8000",
    localToken: tokenEl.value.trim(),
    autoCapture: autoEl.checked,
    parserDiagnostics: diagnosticsToggle.checked,
  });
  sanitizeEl.hidden = !diagnosticsToggle.checked;
  if (!diagnosticsToggle.checked) {
    diagnosticsEl.hidden = true;
  }
}

autoEl.addEventListener("change", saveField);
backendEl.addEventListener("change", saveField);
tokenEl.addEventListener("change", saveField);
diagnosticsToggle.addEventListener("change", async () => {
  await saveField();
  load();
});

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
  applySummary(result);
});

sanitizeEl.addEventListener("click", async () => {
  const tab = await activeSlackTab();
  if (!tab) {
    setStatus("Open Slack Web to sync");
    return;
  }
  try {
    const response = await chrome.tabs.sendMessage(tab.id, { type: "sanitize-dom" });
    if (!response || !response.ok || !response.result) {
      setStatus("Sanitizer unavailable");
      return;
    }
    await navigator.clipboard.writeText(response.result.html || "");
    setStatus("Sanitized DOM copied · review before saving a fixture");
  } catch (_err) {
    setStatus("Reload the extension, then refresh the Slack tab");
  }
});

load();
