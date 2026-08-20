(function () {
  "use strict";

  var DEBOUNCE_MS = 450;
  var HEARTBEAT_MS = 20000;
  var lastSent = {};
  var timer = null;
  var autoCapture = true;
  var heartbeatTimer = null;
  var lastResult = { found: 0, sent: 0, conversation: null, error: null };

  function pageUrl() {
    try {
      return window.top.location.href || location.href || "";
    } catch (_err) {
      return location.href || "";
    }
  }

  function snapshot() {
    if (!globalThis.SlackDomParser) return null;
    return globalThis.SlackDomParser.parseDocument(document, pageUrl());
  }

  function changedMessages(parsed) {
    if (!parsed) return [];
    var outgoing = [];
    parsed.messages.forEach(function (message) {
      var previous = lastSent[message.external_id];
      if (previous === message.text) return;
      lastSent[message.external_id] = message.text;
      outgoing.push(message);
    });
    return outgoing;
  }

  function postToBackground(type, payload) {
    try {
      chrome.runtime.sendMessage({ type: type, payload: payload }, function () {
        void chrome.runtime.lastError;
      });
    } catch (_err) {
      // Extension context can vanish on reload. The next page load reattaches.
    }
  }

  function remember(result) {
    lastResult = result;
    try {
      chrome.storage.local.set({ lastCapture: result });
    } catch (_err) {
      // Ignore storage failures in restricted frames.
    }
  }

  function capture(reason) {
    var parsed = snapshot();
    if (!parsed) {
      remember({ found: 0, sent: 0, conversation: null, error: "parser-missing" });
      return lastResult;
    }
    postToBackground("slack-browser-heartbeat", {
      workspace_present: Boolean(parsed.workspace_present || parsed.conversation),
    });
    if (!autoCapture && reason !== "manual") {
      remember({
        found: parsed.messages.length,
        sent: 0,
        conversation: parsed.conversation && parsed.conversation.external_id,
        error: "auto-off",
      });
      return lastResult;
    }
    var messages = reason === "manual" ? parsed.messages : changedMessages(parsed);
    if (!parsed.conversation) {
      remember({
        found: parsed.messages.length,
        sent: 0,
        conversation: null,
        error: "no-conversation",
      });
      return lastResult;
    }
    if (!messages.length) {
      remember({
        found: parsed.messages.length,
        sent: 0,
        conversation: parsed.conversation.external_id,
        error: parsed.messages.length ? "unchanged" : "no-messages",
      });
      return lastResult;
    }
    postToBackground("slack-browser-events", {
      conversation: parsed.conversation,
      messages: messages,
    });
    remember({
      found: parsed.messages.length,
      sent: messages.length,
      conversation: parsed.conversation.external_id,
      error: null,
    });
    return lastResult;
  }

  function schedule(reason) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      capture(reason);
    }, DEBOUNCE_MS);
  }

  function startObserver() {
    var root = document.body;
    if (!root || root.dataset.casSlackReader === "1") return;
    root.dataset.casSlackReader = "1";
    var observer = new MutationObserver(function (mutations) {
      var relevant = false;
      for (var i = 0; i < mutations.length; i += 1) {
        var mutation = mutations[i];
        if (mutation.type === "characterData") {
          relevant = true;
          break;
        }
        if (mutation.type === "childList" && mutation.addedNodes && mutation.addedNodes.length) {
          relevant = true;
          break;
        }
      }
      if (relevant) schedule("mutation");
    });
    observer.observe(root, { childList: true, subtree: true, characterData: true });
  }

  chrome.storage.local.get({ autoCapture: true }, function (stored) {
    autoCapture = stored.autoCapture !== false;
  });

  chrome.storage.onChanged.addListener(function (changes, area) {
    if (area === "local" && changes.autoCapture) {
      autoCapture = changes.autoCapture.newValue !== false;
    }
  });

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || !message.type) return;
    if (message.type === "capture-now") {
      sendResponse(capture("manual"));
      return true;
    }
    if (message.type === "ping-tab") {
      var parsed = snapshot();
      sendResponse({
        ok: true,
        url: pageUrl(),
        found: parsed ? parsed.messages.length : 0,
        conversation: parsed && parsed.conversation ? parsed.conversation.external_id : null,
        last: lastResult,
      });
      return true;
    }
  });

  startObserver();
  capture("initial");
  heartbeatTimer = setInterval(function () {
    var parsed = snapshot();
    postToBackground("slack-browser-heartbeat", {
      workspace_present: Boolean(parsed && (parsed.workspace_present || parsed.conversation)),
    });
  }, HEARTBEAT_MS);
})();
