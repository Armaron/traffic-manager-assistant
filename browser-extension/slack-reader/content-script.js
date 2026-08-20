(function () {
  "use strict";

  if (window.top !== window.self) {
    return;
  }

  var DEBOUNCE_MS = 450;
  var HEARTBEAT_MS = 20000;
  var lastSent = {};
  var timer = null;
  var autoCapture = true;
  var diagnosticsEnabled = false;
  var heartbeatTimer = null;
  var paneObserver = null;
  var rootObserver = null;
  var paneNode = null;
  var lastConversationKey = "";
  var lastResult = {
    found: 0,
    sent: 0,
    skipped: 0,
    candidates: 0,
    canonical: 0,
    conversation: null,
    conversationDetected: false,
    error: null,
  };

  function pageUrl() {
    try {
      return window.top.location.href || location.href || "";
    } catch (_err) {
      return location.href || "";
    }
  }

  function conversationKey() {
    if (!globalThis.SlackDomParser) return "";
    if (globalThis.SlackDomParser.activeConversationId) {
      return globalThis.SlackDomParser.activeConversationId(document, pageUrl()) || "";
    }
    return globalThis.SlackDomParser.conversationIdFromUrl(pageUrl()) || "";
  }

  function snapshot() {
    if (!globalThis.SlackDomParser) return null;
    return globalThis.SlackDomParser.parseDocument(document, pageUrl());
  }

  function cacheKey(conversationId, messageId) {
    return String(conversationId || "") + "::" + String(messageId || "");
  }

  function fingerprint(message) {
    if (globalThis.SlackDomParser && globalThis.SlackDomParser.semanticFingerprint) {
      return globalThis.SlackDomParser.semanticFingerprint(message);
    }
    return [message.text, message.sender_external_id, message.sender_name, message.direction, message.thread_external_id, message.attachment_placeholder, message.deleted].join("\u0000");
  }

  function toPayloadMessage(message) {
    return {
      external_id: message.external_id,
      sender_external_id: message.sender_external_id,
      sender_name: message.sender_name,
      timestamp: message.timestamp,
      text: message.text,
      direction: message.direction,
      thread_external_id: message.thread_external_id,
      browser_fallback_id: Boolean(message.browser_fallback_id),
      attachment_placeholder: message.attachment_placeholder || null,
      deleted: Boolean(message.deleted),
    };
  }

  function changedMessages(parsed) {
    if (!parsed) return [];
    var conversationId = parsed.conversation && parsed.conversation.external_id;
    var outgoing = [];
    parsed.messages.forEach(function (message) {
      var key = cacheKey(conversationId, message.external_id);
      var next = fingerprint(message);
      if (lastSent[key] === next) return;
      lastSent[key] = next;
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

  function diagnosticsFrom(parsed, extra) {
    var diag = (parsed && parsed.diagnostics) || {};
    var result = {
      found: parsed ? parsed.messages.length : 0,
      sent: extra && extra.sent ? extra.sent : 0,
      skipped: diag.skipped_low_confidence || 0,
      candidates: diag.candidates || 0,
      canonical: diag.canonical_roots || 0,
      parsed: diag.parsed || (parsed ? parsed.messages.length : 0),
      stable_ts: diag.stable_ts || 0,
      fallback_ids: diag.fallback_ids || 0,
      inherited_sender: diag.inherited_sender || 0,
      unknown_direction: diag.unknown_direction || 0,
      missing_sender: diag.missing_sender || 0,
      conversation: parsed && parsed.conversation ? parsed.conversation.external_id : null,
      conversationDetected: Boolean(parsed && parsed.conversation),
      error: extra && extra.error ? extra.error : null,
    };
    if (diagnosticsEnabled && diag.items) {
      result.items = diag.items;
    }
    return result;
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
      remember({ found: 0, sent: 0, skipped: 0, candidates: 0, canonical: 0, conversation: null, conversationDetected: false, error: "parser-missing" });
      return lastResult;
    }
    postToBackground("slack-browser-heartbeat", {
      workspace_present: Boolean(parsed.workspace_present || parsed.conversation),
    });
    if (!autoCapture && reason !== "manual") {
      remember(diagnosticsFrom(parsed, { sent: 0, error: "auto-off" }));
      return lastResult;
    }
    var messages = reason === "manual" ? parsed.messages : changedMessages(parsed);
    if (reason === "manual") {
      var conversationId = parsed.conversation && parsed.conversation.external_id;
      parsed.messages.forEach(function (message) {
        lastSent[cacheKey(conversationId, message.external_id)] = fingerprint(message);
      });
    }
    if (!parsed.conversation) {
      remember(diagnosticsFrom(parsed, { sent: 0, error: "no-conversation" }));
      return lastResult;
    }
    if (!messages.length) {
      remember(
        diagnosticsFrom(parsed, {
          sent: 0,
          error: parsed.messages.length ? "unchanged" : "no-messages",
        })
      );
      return lastResult;
    }
    postToBackground("slack-browser-events", {
      conversation: parsed.conversation,
      messages: messages.map(toPayloadMessage),
    });
    remember(diagnosticsFrom(parsed, { sent: messages.length, error: null }));
    return lastResult;
  }

  function schedule(reason) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      capture(reason);
    }, DEBOUNCE_MS);
  }

  function attachPaneObserver() {
    if (!globalThis.SlackDomParser) return;
    var pane = globalThis.SlackDomParser.findMessagePane(document);
    if (paneObserver && pane === paneNode) return;
    if (paneObserver) {
      paneObserver.disconnect();
      paneObserver = null;
    }
    paneNode = pane;
    if (!pane) return;
    paneObserver = new MutationObserver(function (mutations) {
      var relevant = false;
      for (var i = 0; i < mutations.length; i += 1) {
        if (globalThis.SlackDomParser.isSemanticMutation(mutations[i], pane)) {
          relevant = true;
          break;
        }
      }
      if (relevant) schedule("mutation");
    });
    paneObserver.observe(pane, { childList: true, subtree: true, characterData: true });
  }

  function startRootObserver() {
    if (rootObserver || !document.body) return;
    lastConversationKey = conversationKey();
    attachPaneObserver();
    rootObserver = new MutationObserver(function () {
      var nextKey = conversationKey();
      var pane = globalThis.SlackDomParser ? globalThis.SlackDomParser.findMessagePane(document) : null;
      if (nextKey !== lastConversationKey || pane !== paneNode) {
        lastConversationKey = nextKey;
        attachPaneObserver();
        schedule("conversation-change");
      }
    });
    rootObserver.observe(document.body, { childList: true, subtree: true, characterData: false });
  }

  chrome.storage.local.get({ autoCapture: true, parserDiagnostics: false }, function (stored) {
    autoCapture = stored.autoCapture !== false;
    diagnosticsEnabled = stored.parserDiagnostics === true;
  });

  chrome.storage.onChanged.addListener(function (changes, area) {
    if (area !== "local") return;
    if (changes.autoCapture) autoCapture = changes.autoCapture.newValue !== false;
    if (changes.parserDiagnostics) diagnosticsEnabled = changes.parserDiagnostics.newValue === true;
  });

  chrome.runtime.onMessage.addListener(function (message, _sender, sendResponse) {
    if (!message || !message.type) return;
    if (message.type === "capture-now") {
      sendResponse(capture("manual"));
      return true;
    }
    if (message.type === "ping-tab") {
      var parsed = snapshot();
      var diag = diagnosticsFrom(parsed, { sent: lastResult.sent, error: lastResult.error });
      sendResponse({
        ok: true,
        url: pageUrl(),
        found: diag.found,
        conversation: diag.conversation,
        last: lastResult,
        diagnostics: diag,
      });
      return true;
    }
    if (message.type === "sanitize-dom") {
      if (!globalThis.SlackDomParser || !globalThis.SlackDomParser.sanitizeCurrentSlackDom) {
        sendResponse({ ok: false, error: "parser-missing" });
        return true;
      }
      sendResponse({ ok: true, result: globalThis.SlackDomParser.sanitizeCurrentSlackDom(document, pageUrl()) });
      return true;
    }
  });

  startRootObserver();
  capture("initial");
  heartbeatTimer = setInterval(function () {
    var parsed = snapshot();
    postToBackground("slack-browser-heartbeat", {
      workspace_present: Boolean(parsed && (parsed.workspace_present || parsed.conversation)),
    });
  }, HEARTBEAT_MS);
})();
