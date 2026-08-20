/**
 * Isolated Slack DOM parser. All Slack selectors live in this file.
 * Reads rendered DOM only. Never cookies, storage credentials, or Slack tokens.
 */
(function (root) {
  "use strict";

  var SLACK_TS_RE = /^\d{9,12}\.\d+$/;
  var EMBEDDED_TS_RE = /(\d{9,12}\.\d+)/;
  var CLIENT_CONV_RE = /\/client\/(?:[ET][A-Z0-9]+\/)+([CDG][A-Z0-9]+)/i;
  var ARCHIVES_CONV_RE = /\/archives\/([CDG][A-Z0-9]+)/i;
  var CHANNEL_QUERY_RE = /[?&](?:channel|cid)=([CDG][A-Z0-9]+)/i;
  var THREAD_URL_RE = /\/thread\/[CDG][A-Z0-9]+-(\d+\.\d+)/i;
  var PERMALINK_TS_RE = /\/p(\d{10})(\d+)/;
  var DELETED_RE = /this message was deleted/i;
  var DATE_DIVIDER_RE =
    /^(?:today|yesterday|tomorrow|сегодня|вчера|завтра|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|понедельник|вторник|среда|четверг|пятница|суббота|воскресенье),?\s+(?:(?:january|february|march|april|may|june|july|august|september|october|november|december|января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+)?\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?|\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)$/i;
  var CLOCK_RE = /^\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?\.?\s*/i;
  var TIME_ONLY_RE = /^\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?\.?$/i;
  var PLACEHOLDER_SENDERS = {
    "name and last name": true,
    "full name": true,
    "display name": true,
    unknown: true,
    user: true,
    member: true,
  };
  var UI_NOISE = { new: true, unread: true, "jump to date": true, "jump to the most recent": true };

  function isSlackTs(value) {
    return typeof value === "string" && SLACK_TS_RE.test(value);
  }

  function conversationIdFromUrl(url) {
    if (!url) return null;
    var match = url.match(CLIENT_CONV_RE) || url.match(ARCHIVES_CONV_RE) || url.match(CHANNEL_QUERY_RE);
    return match ? match[1] : null;
  }

  function tsFromToken(value) {
    if (!value) return null;
    if (isSlackTs(value)) return value;
    var match = String(value).match(EMBEDDED_TS_RE);
    return match ? match[1] : null;
  }

  function conversationTypeFromId(conversationId) {
    var prefix = String(conversationId || "").charAt(0).toUpperCase();
    if (prefix === "D") return "direct";
    if (prefix === "C") return "channel";
    if (prefix === "G") return "group";
    return "group";
  }

  function threadIdFromUrl(url) {
    var match = String(url || "").match(THREAD_URL_RE);
    return match ? match[1] : null;
  }

  function timestampFromPermalink(href) {
    if (!href) return null;
    var match = href.match(PERMALINK_TS_RE);
    return match ? match[1] + "." + match[2] : null;
  }

  function fallbackMessageId(conversationId, timestamp, sender, text) {
    var material = conversationId + "\n" + timestamp + "\n" + sender + "\n" + text;
    return "b_" + fnvHex(material);
  }

  function fnvHex(text) {
    var h1 = 0x811c9dc5;
    var h2 = 0x811c9dc5;
    for (var i = 0; i < text.length; i += 1) {
      var code = text.charCodeAt(i);
      h1 ^= code;
      h1 = Math.imul(h1, 0x01000193);
      h2 ^= code + i;
      h2 = Math.imul(h2, 0x01000193);
    }
    return (toHex(h1) + toHex(h2) + toHex(h1 ^ h2) + toHex(~h2)).slice(0, 32);
  }

  function toHex(value) {
    return (value >>> 0).toString(16).padStart(8, "0");
  }

  async function shaFallback(conversationId, timestamp, sender, text) {
    if (!root.crypto || !root.crypto.subtle) {
      return fallbackMessageId(conversationId, timestamp, sender, text);
    }
    var material = conversationId + "\n" + timestamp + "\n" + sender + "\n" + text;
    var bytes = new TextEncoder().encode(material);
    var digest = await root.crypto.subtle.digest("SHA-256", bytes);
    var hex = Array.from(new Uint8Array(digest))
      .map(function (b) {
        return b.toString(16).padStart(2, "0");
      })
      .join("")
      .slice(0, 32);
    return "b_" + hex;
  }

  function normalizeText(value) {
    return String(value || "")
      .replace(/\r\n/g, "\n")
      .replace(/[ \t]+/g, " ")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  function collapsedName(value) {
    return String(value || "").replace(/\s+/g, "").toLowerCase();
  }

  function namesMatch(left, right) {
    var a = normalizeText(left);
    var b = normalizeText(right);
    if (!a || !b) return false;
    var ca = collapsedName(a);
    var cb = collapsedName(b);
    if (ca === cb) return true;
    var shorter = ca.length <= cb.length ? ca : cb;
    var longer = ca.length <= cb.length ? cb : ca;
    if (shorter.length >= 4 && longer.indexOf(shorter) === 0) return true;
    var wordsA = a.toLowerCase().split(/\s+/);
    var wordsB = b.toLowerCase().split(/\s+/);
    if (wordsA[0] && wordsB[0] && wordsA[0] === wordsB[0] && wordsA[0].length >= 3) {
      if (wordsA.length === 1 || wordsB.length === 1) return true;
    }
    return false;
  }

  function cleanSenderName(value) {
    var name = normalizeText(value);
    if (!name) return null;
    name = name.split("\n")[0].trim();
    name = name.replace(/^(user menu for|account for|logged in as)\s+/i, "");
    var tokens = name.split(/\s+/);
    if (tokens[0]) {
      var re = new RegExp(tokens[0].replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "ig");
      var match;
      var matches = [];
      while ((match = re.exec(name))) {
        matches.push(match);
        if (matches.length >= 2) break;
      }
      if (matches.length >= 2 && matches[0].index === 0) {
        var left = name.slice(0, matches[1].index).trim();
        var right = name.slice(matches[1].index).trim();
        if (namesMatch(left, right)) name = left;
      }
    }
    var half = Math.floor(name.length / 2);
    if (half >= 4 && name.slice(0, half).toLowerCase() === name.slice(half).toLowerCase()) {
      name = name.slice(0, half).trim();
    }
    var compact = collapsedName(name);
    var mid = Math.floor(compact.length / 2);
    if (mid >= 4 && compact.slice(0, mid) === compact.slice(mid)) {
      name = name.slice(0, Math.max(1, Math.floor(name.length / 2))).trim();
    }
    if (PLACEHOLDER_SENDERS[name.toLowerCase()]) return null;
    return name || null;
  }

  function stripMessageChrome(text, senderName) {
    var cleaned = normalizeText(text);
    var previous = null;
    while (cleaned && cleaned !== previous) {
      previous = cleaned;
      if (senderName) {
        var prefix = normalizeText(senderName);
        if (prefix && cleaned.toLowerCase().indexOf(prefix.toLowerCase()) === 0) {
          cleaned = cleaned.slice(prefix.length).replace(/^[ :,\-]+/, "");
          continue;
        }
      }
      var stripped = cleaned.replace(CLOCK_RE, "").replace(/^[ :.\-]+/, "");
      if (stripped !== cleaned) {
        cleaned = stripped;
        continue;
      }
      break;
    }
    cleaned = cleaned.replace(/(?:\d{1,2}:\d{2}(?:\s*[ap]m)?){2,}/gi, "");
    return normalizeText(cleaned);
  }

  function isNoiseText(text) {
    var value = normalizeText(text);
    if (!value) return true;
    if (value === "[Image]" || value === "[File]" || value === "[Deleted Slack message]") return false;
    var lowered = value.toLowerCase();
    if (DATE_DIVIDER_RE.test(value) || PLACEHOLDER_SENDERS[lowered] || UI_NOISE[lowered]) return true;
    if (TIME_ONLY_RE.test(value)) return true;
    if (CLOCK_RE.test(value) && !/[a-zа-яё]/i.test(value.replace(CLOCK_RE, ""))) return true;
    return false;
  }

  function visibleText(node) {
    if (!node) return "";
    if (node.getAttribute && node.getAttribute("aria-hidden") === "true") return "";
    if (node.classList && (node.classList.contains("offscreen") || String(node.className || "").indexOf("offscreen") !== -1)) {
      return "";
    }
    var parts = [];
    node.childNodes.forEach(function (child) {
      if (child.nodeType === 3) {
        parts.push(child.textContent || "");
        return;
      }
      if (child.nodeType !== 1) return;
      if (child.tagName === "SCRIPT" || child.tagName === "STYLE") return;
      if (child.tagName === "BR") {
        parts.push("\n");
        return;
      }
      parts.push(visibleText(child));
    });
    return parts.join("");
  }

  function findConversationRoot(doc) {
    return (
      doc.querySelector('[data-qa="slack-conversation"]') ||
      doc.querySelector('[data-qa="message_pane"]') ||
      doc.querySelector('[data-qa="page_contents"]') ||
      doc.querySelector(".p-message_pane") ||
      doc.querySelector("[data-channel-id]") ||
      doc.body
    );
  }

  function parseCurrentUser(root) {
    var node =
      root.querySelector('[data-qa="current-user"]') ||
      root.querySelector('[data-qa="user-button"]') ||
      root.querySelector('[data-qa="account-button"]') ||
      root.querySelector('[data-qa="account-switcher-button"]') ||
      document.querySelector('[data-qa="current-user"]') ||
      document.querySelector('[data-qa="user-button"]') ||
      document.querySelector('[data-qa="account-button"]') ||
      document.querySelector('[data-qa="account-switcher-button"]');
    if (!node) return { external_id: null, name: null };
    return {
      external_id: node.getAttribute("data-user-id") || node.getAttribute("data-entity-id") || null,
      name: cleanSenderName(
        node.getAttribute("data-user-name") || node.getAttribute("aria-label") || visibleText(node)
      ),
    };
  }

  function isDivider(node) {
    var qa = (node.getAttribute("data-qa") || "").toLowerCase();
    var id = (node.id || "").toLowerCase();
    var className = String(node.className || "").toLowerCase();
    if (qa.indexOf("divider") !== -1 || qa.indexOf("unread") !== -1 || qa.indexOf("start_of_history") !== -1 || qa.indexOf("day_heading") !== -1) return true;
    if (className.indexOf("date_divider") !== -1 || className.indexOf("unread__separator") !== -1 || className.indexOf("c-message_list__day_divider") !== -1) return true;
    if (id.indexOf("date") !== -1 && !tsFromToken(node.id)) return true;
    var label = normalizeText(visibleText(node));
    if (DATE_DIVIDER_RE.test(label) && !hasMessageSignal(node)) return true;
    return false;
  }

  function hasMessageSignal(node) {
    if (isSlackTs(tsFromToken(node.getAttribute("data-ts") || node.getAttribute("data-item-key") || node.id))) return true;
    if ((node.getAttribute("role") || "").toLowerCase() === "message") return true;
    var qa = node.getAttribute("data-qa") || "";
    if (qa === "message_container" || qa === "message-container") return true;
    return Boolean(
      node.querySelector(
        '[data-qa="message_container"], [data-qa="message-container"], [data-qa="message-text"], [data-qa="message_text"], [data-qa="message_content"], [role="message"], .c-timestamp, .c-message_kit__message, .p-rich_text_section, [data-ts], a.c-timestamp'
      )
    );
  }

  function looksLikeMessage(node) {
    if (!node || node.nodeType !== 1 || isDivider(node)) return false;
    var qa = node.getAttribute("data-qa") || "";
    if (qa === "virtual-list-item" || qa === "virtual_list_item") return hasMessageSignal(node);
    if (qa === "message_container" || qa === "message-container") return true;
    if ((node.getAttribute("role") || "").toLowerCase() === "message") return true;
    if (node.id && node.id.indexOf("message-list") === 0 && tsFromToken(node.id)) return true;
    if (node.classList && (node.classList.contains("c-message_kit__background") || node.classList.contains("c-message_kit__message"))) {
      return true;
    }
    if (node.classList && node.classList.contains("c-virtual_list__item") && tsFromToken(node.getAttribute("data-item-key") || node.id)) {
      return true;
    }
    return Boolean(tsFromToken(node.getAttribute("data-ts") || node.getAttribute("data-item-key")));
  }

  function findRenderedMessages(root) {
    var threadPane = root.querySelector('[data-qa="threads_flexpane"]');
    var pane = root.querySelector('[data-qa="message_pane"]') || root.querySelector(".p-message_pane") || root;
    if (
      threadPane &&
      threadPane.querySelector('[data-qa="message_container"], [id^="message-list"], [role="message"], .c-message_kit__message')
    ) {
      pane = threadPane;
    }
    var selectors = [
      '[data-qa="message_container"]',
      '[data-qa="message-container"]',
      '[data-qa="virtual-list-item"]',
      '[data-qa="virtual_list_item"]',
      '[id^="message-list"]',
      '[role="message"]',
      ".c-message_kit__background",
      ".c-message_kit__message",
      ".c-virtual_list__item",
    ];
    var nodes = [];
    var seen = [];
    function add(node) {
      if (!looksLikeMessage(node) || seen.indexOf(node) !== -1) return;
      seen.push(node);
      nodes.push(node);
    }
    selectors.forEach(function (selector) {
      Array.prototype.slice.call(pane.querySelectorAll(selector)).forEach(add);
    });
    if (!nodes.length && pane !== root) {
      selectors.forEach(function (selector) {
        Array.prototype.slice.call(root.querySelectorAll(selector)).forEach(add);
      });
    }
    return nodes;
  }

  function parseSender(node) {
    var sender = node.querySelector(
      '[data-qa="message_sender"], [data-qa="message_sender_name"], .c-message__sender, .c-message_kit__sender, button.c-message__sender_button'
    );
    if (sender) {
      return {
        external_id: sender.getAttribute("data-user-id") || node.getAttribute("data-user-id") || null,
        name: cleanSenderName(normalizeText(visibleText(sender)) || sender.getAttribute("data-user-name")),
      };
    }
    return {
      external_id: node.getAttribute("data-user-id") || node.getAttribute("data-message-sender-id") || null,
      name: cleanSenderName(node.getAttribute("data-user-name")),
    };
  }

  function parseTimestamp(node) {
    var direct = tsFromToken(node.getAttribute("data-ts") || node.getAttribute("data-item-key") || node.id);
    if (direct) return direct;
    var stamped = node.querySelector("[data-ts], a.c-timestamp, time[datetime], [id^='message-list']");
    if (stamped) {
      var ts = tsFromToken(stamped.getAttribute("data-ts") || stamped.id);
      if (ts) return ts;
      var permalink = timestampFromPermalink(stamped.getAttribute("href"));
      if (permalink) return permalink;
      if (stamped.getAttribute("datetime")) return stamped.getAttribute("datetime");
    }
    return null;
  }

  function parseThreadMarker(node, pageUrl) {
    var threadTs = node.getAttribute("data-thread-ts") || node.getAttribute("data-thread-id");
    var ownTs = node.getAttribute("data-ts");
    if (threadTs && threadTs !== ownTs) return threadTs;
    var urlThread = threadIdFromUrl(pageUrl);
    if (urlThread && urlThread !== ownTs) return urlThread;
    var reply = node.querySelector("[data-thread-ts]");
    if (reply && reply.getAttribute("data-thread-ts") !== ownTs) {
      return reply.getAttribute("data-thread-ts");
    }
    return null;
  }

  function isAvatarImage(el) {
    var className = String(el.className || "").toLowerCase();
    var qa = (el.getAttribute("data-qa") || "").toLowerCase();
    var alt = (el.getAttribute("alt") || "").toLowerCase();
    if (className.indexOf("c-avatar") !== -1 || className.indexOf("c-base_icon") !== -1 || className.indexOf("c-presence") !== -1) return true;
    if (qa.indexOf("avatar") !== -1 || qa.indexOf("member_image") !== -1 || qa.indexOf("user_image") !== -1) return true;
    if (alt.indexOf("avatar") !== -1 || alt.indexOf("presence") !== -1) return true;
    return false;
  }

  function parseVisibleAttachments(node) {
    if (node.querySelector('[data-qa="image_attachment"], [data-attachment-kind="image"]')) return "image";
    if (node.querySelector('[data-qa="file_attachment"], [data-qa="file_stub"], [data-qa="file_name"]')) return "file";
    var images = node.querySelectorAll("img");
    for (var i = 0; i < images.length; i += 1) {
      if (isAvatarImage(images[i])) continue;
      var src = (images[i].getAttribute("src") || "").toLowerCase();
      var alt = (images[i].getAttribute("alt") || "").toLowerCase();
      var className = String(images[i].className || "").toLowerCase();
      if (alt.indexOf("file thumbnail") !== -1 || alt.indexOf("image attachment") !== -1 || alt.indexOf("uploaded") !== -1) {
        return "image";
      }
      if (className.indexOf("c-pillow_file") !== -1 || className.indexOf("p-file_image") !== -1 || className.indexOf("file_preview") !== -1) {
        return "image";
      }
      if (src.indexOf("files.slack.com") !== -1 || src.indexOf("slack-files.com") !== -1 || src.indexOf("files-origin.slack.com") !== -1) {
        return "image";
      }
    }
    return null;
  }

  function parseText(node) {
    var block = node.querySelector(
      '[data-qa="message-text"], [data-qa="message_text"], .p-rich_text_section, .c-message_kit__text, .c-message__body, [data-qa="message_content"]'
    );
    if (block) return normalizeText(visibleText(block));
    var clone = node.cloneNode(true);
    clone.querySelectorAll('[data-qa="message_sender"], [data-qa="message_sender_name"], [data-qa="image_attachment"], [data-qa="file_attachment"], [data-qa="file_stub"], [data-qa="file_name"], .c-timestamp, .c-message__sender_button, .c-message__sender, .c-message_kit__sender, time, img').forEach(function (el) {
      el.remove();
    });
    return normalizeText(visibleText(clone));
  }

  function directionFor(node, sender, currentUser) {
    var explicit = node.getAttribute("data-from-current-user");
    if (explicit === "true") return "outgoing";
    if (explicit === "false") return "incoming";
    if (node.classList && (node.classList.contains("c-message--me") || String(node.className || "").indexOf("--mine") !== -1)) {
      return "outgoing";
    }
    if (currentUser.external_id && sender.external_id) {
      return sender.external_id === currentUser.external_id ? "outgoing" : "incoming";
    }
    if (namesMatch(sender.name, currentUser.name)) return "outgoing";
    if (cleanSenderName(sender.name) && cleanSenderName(currentUser.name)) return "incoming";
    return "unknown";
  }

  function parseConversation(root, url) {
    var convRoot = findConversationRoot(root);
    var urlId = conversationIdFromUrl(url);
    var attrId = convRoot && convRoot.getAttribute("data-channel-id");
    var externalId = attrId || urlId;
    if (!externalId) return null;
    var name = (convRoot && convRoot.getAttribute("data-channel-name")) || "";
    var header =
      (convRoot && convRoot.querySelector('[data-qa="channel_name"], [data-qa="channel_name_button"], [data-qa="dm_title"]')) ||
      document.querySelector('[data-qa="channel_name_button"], [data-qa="channel_name"], [data-qa="dm_title"]');
    if (header) name = name || normalizeText(visibleText(header));
    var convType = (convRoot && convRoot.getAttribute("data-channel-type")) || conversationTypeFromId(externalId);
    return {
      external_id: externalId,
      name: name || externalId,
      type: convType === "channel" || convType === "direct" || convType === "group" ? convType : "group",
    };
  }

  function parseMessageNode(node, conversationId, currentUser, pageUrl) {
    var sender = parseSender(node);
    var senderName = cleanSenderName(sender.name);
    var timestamp = parseTimestamp(node) || "";
    var text = stripMessageChrome(parseText(node), senderName);
    var placeholder = parseVisibleAttachments(node);
    var deleted = DELETED_RE.test(text);
    if (deleted) text = "[Deleted Slack message]";
    else if (!text && placeholder === "image") text = "[Image]";
    else if (!text && placeholder === "file") text = "[File]";
    else if (placeholder === "image" && text.indexOf("[Image]") === -1) text = text ? text + "\n[Image]" : "[Image]";
    else if (placeholder === "file" && text.indexOf("[File]") === -1) text = text ? text + "\n[File]" : "[File]";
    if (isNoiseText(text) && !placeholder) return null;
    if (!text && !placeholder) return null;
    var slackId = tsFromToken(node.getAttribute("data-ts") || node.getAttribute("data-item-key") || node.id);
    if (!isSlackTs(slackId)) slackId = isSlackTs(timestamp) ? timestamp : null;
    var browserFallback = false;
    var externalId = slackId;
    if (!externalId) {
      externalId = fallbackMessageId(conversationId, timestamp, sender.external_id || senderName || "", text);
      browserFallback = true;
    }
    return {
      external_id: externalId,
      sender_external_id: sender.external_id,
      sender_name: senderName,
      timestamp: timestamp || externalId,
      text: text,
      direction: directionFor(node, sender, currentUser),
      thread_external_id: parseThreadMarker(node, pageUrl),
      browser_fallback_id: browserFallback,
      attachment_placeholder: placeholder,
      deleted: deleted,
    };
  }

  function parseDocument(doc, url) {
    var conversation = parseConversation(doc, url);
    var currentUser = parseCurrentUser(doc);
    var conversationId = (conversation && conversation.external_id) || conversationIdFromUrl(url) || "unknown";
    var messages = [];
    var seen = {};
    var searchRoot = doc.body || doc;
    findRenderedMessages(searchRoot).forEach(function (node) {
      var parsed = parseMessageNode(node, conversationId, currentUser, url);
      if (!parsed || seen[parsed.external_id]) return;
      seen[parsed.external_id] = true;
      messages.push(parsed);
    });
    return {
      conversation: conversation,
      current_user: currentUser,
      messages: messages,
      workspace_present: Boolean(conversation || conversationIdFromUrl(url)),
    };
  }

  root.SlackDomParser = {
    parseDocument: parseDocument,
    findConversationRoot: findConversationRoot,
    findRenderedMessages: findRenderedMessages,
    parseMessageNode: parseMessageNode,
    parseSender: parseSender,
    parseTimestamp: parseTimestamp,
    parseText: parseText,
    parseThreadMarker: parseThreadMarker,
    parseVisibleAttachments: parseVisibleAttachments,
    conversationIdFromUrl: conversationIdFromUrl,
    fallbackMessageId: fallbackMessageId,
    shaFallback: shaFallback,
    isSlackTs: isSlackTs,
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
