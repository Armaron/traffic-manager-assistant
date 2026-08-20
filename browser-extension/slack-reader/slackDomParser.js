/**
 * Isolated Slack DOM parser. All Slack selectors live in this file.
 * Reads rendered DOM only. Never cookies, storage credentials, or Slack tokens.
 */
(function (root) {
  "use strict";

  var SLACK_TS_RE = /^\d{9,12}\.\d+$/;
  var EMBEDDED_TS_RE = /(\d{9,12}\.\d+)/;
  var CLIENT_CONV_RE = /\/client\/(?:[ET][A-Z0-9]+\/)+([CDG][A-Z0-9]+)/i;
  var CLIENT_CONV_LOOSE_RE = /\/client\/(?:[^/?#]+\/)*([CDG][A-Z0-9]{8,})/i;
  var ARCHIVES_CONV_RE = /\/archives\/([CDG][A-Z0-9]+)/i;
  var CONV_ID_RE = /^[CDG][A-Z0-9]{6,}$/i;
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
  var BODY_SELECTORS = [
    '[data-qa="message-text"]',
    '[data-qa="message_text"]',
    ".p-rich_text_section",
    ".c-message_kit__text",
    ".c-message__body",
    '[data-qa="message_content"]',
  ];
  var SENDER_SELECTOR =
    '[data-qa="message_sender"], [data-qa="message_sender_name"], .c-message_kit__sender, button.c-message__sender_button, .c-message__sender';
  var CHROME_QA =
    /^(hover|message_actions|emoji-bar|reaction|save_message|share_message|more_actions|reply_in_thread|reply_bar|thread_replies|bookmark|pin|unread|date_divider|day_heading)/i;
  var CANDIDATE_SELECTORS = [
    '[data-qa="virtual-list-item"]',
    '[data-qa="virtual_list_item"]',
    ".c-virtual_list__item",
    '[data-qa="message_container"]',
    '[data-qa="message-container"]',
    "[id^='message-list']",
    ".c-message_kit__background",
    ".c-message_kit__message",
    '[role="message"]',
  ];
  var DIVIDER_SELECTORS = [
    '[data-qa="date_divider"]',
    '[data-qa="unread_divider"]',
    '[data-qa="start_of_history"]',
    ".c-message_list__day_divider",
    ".c-message_list__unread_divider",
    ".p-message_pane__unread_divider",
  ];

  function isSlackTs(value) {
    return typeof value === "string" && SLACK_TS_RE.test(value);
  }

  function isConversationId(value) {
    return typeof value === "string" && CONV_ID_RE.test(value);
  }

  function conversationIdFromUrl(url) {
    if (!url) return null;
    var match =
      url.match(CLIENT_CONV_RE) ||
      url.match(CLIENT_CONV_LOOSE_RE) ||
      url.match(ARCHIVES_CONV_RE) ||
      url.match(CHANNEL_QUERY_RE);
    return match && isConversationId(match[1]) ? match[1] : null;
  }

  function isInSidebar(node) {
    if (!node || !node.closest) return false;
    return Boolean(node.closest('[data-qa="channel_sidebar"], .p-channel_sidebar, nav.p-channel_sidebar'));
  }

  function conversationIdFromLinks(root) {
    if (!root || !root.querySelectorAll) return null;
    var counts = {};
    Array.prototype.forEach.call(root.querySelectorAll("a[href]"), function (link) {
      if (isInSidebar(link)) return;
      var id = conversationIdFromUrl(link.getAttribute("href") || "");
      if (!id) return;
      counts[id] = (counts[id] || 0) + 1;
    });
    var best = null;
    var bestCount = 0;
    Object.keys(counts).forEach(function (id) {
      if (counts[id] > bestCount) {
        best = id;
        bestCount = counts[id];
      }
    });
    return best;
  }

  function conversationIdFromNode(node) {
    if (!node || !node.getAttribute) return null;
    var id = node.getAttribute("data-channel-id") || node.getAttribute("data-entity-id");
    return isConversationId(id) ? id : null;
  }

  function conversationIdFromPane(pane) {
    if (!pane) return null;
    var own = conversationIdFromNode(pane);
    if (own) return own;
    var nodes = pane.querySelectorAll ? pane.querySelectorAll("[data-channel-id], [data-entity-id]") : [];
    for (var i = 0; i < nodes.length; i += 1) {
      if (isInSidebar(nodes[i]) || nodes[i].getAttribute("data-ts")) continue;
      var id = conversationIdFromNode(nodes[i]);
      if (id) return id;
    }
    var fromLinks = conversationIdFromLinks(pane);
    if (fromLinks) return fromLinks;
    var parent = pane.parentElement;
    while (parent && parent.getAttribute) {
      if (isInSidebar(parent)) break;
      var parentId = conversationIdFromNode(parent);
      if (parentId) return parentId;
      parent = parent.parentElement;
    }
    return null;
  }

  function conversationIdFromHeader(doc) {
    if (!doc || !doc.querySelector) return null;
    var header = doc.querySelector(
      '[data-qa="channel_name_button"], [data-qa="channel_name"], [data-qa="dm_title"], .p-view_header'
    );
    if (!header) return null;
    var href = header.getAttribute("href");
    var link = header.querySelector && header.querySelector("a[href]");
    if (!href && link) href = link.getAttribute("href");
    return conversationIdFromUrl(href || "");
  }

  function activeConversationId(doc, url) {
    var pane = findMessagePane(doc);
    var paneId = conversationIdFromPane(pane);
    if (paneId) return paneId;
    var headerId = conversationIdFromHeader(doc);
    if (headerId) return headerId;
    var linkId = conversationIdFromLinks(doc);
    if (linkId) return linkId;
    return conversationIdFromUrl(url);
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
    name = name.replace(/^(user menu for|account for|logged in as|direct message with)\s+/i, "");
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
    var collapsed = collapsedName(name);
    var mid = Math.floor(collapsed.length / 2);
    if (mid >= 4 && collapsed.slice(0, mid) === collapsed.slice(mid)) {
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
    if (/^(add reaction|reply|reply in thread|more actions|save for later|forward|share|edited|\d+\s+replies?)$/i.test(value))
      return true;
    if (CLOCK_RE.test(value) && !/[a-zа-яё]/i.test(value.replace(CLOCK_RE, ""))) return true;
    return false;
  }

  function isHiddenElement(node) {
    if (!node || node.nodeType !== 1) return false;
    if (node.getAttribute("aria-hidden") === "true" || node.hasAttribute("hidden")) return true;
    var cls = String(node.className || "").toLowerCase();
    if (cls.indexOf("offscreen") !== -1 || cls.indexOf("sr-only") !== -1 || cls.indexOf("c-offscreen") !== -1) return true;
    var style = node.getAttribute("style") || "";
    if (/display\s*:\s*none/i.test(style) || /visibility\s*:\s*hidden/i.test(style)) return true;
    return false;
  }

  function isChromeNode(node) {
    if (!node || node.nodeType !== 1) return false;
    var qa = node.getAttribute("data-qa") || "";
    if (CHROME_QA.test(qa) || /divider|unread|toolbar|actions/i.test(qa)) return true;
    var cls = String(node.className || "").toLowerCase();
    if (
      cls.indexOf("c-message_actions") !== -1 ||
      cls.indexOf("c-reaction") !== -1 ||
      cls.indexOf("c-icon_button") !== -1 ||
      cls.indexOf("c-timestamp") !== -1 ||
      cls.indexOf("c-message_kit__reactions") !== -1 ||
      cls.indexOf("c-message_list__day_divider") !== -1 ||
      cls.indexOf("unread__separator") !== -1
    ) {
      return true;
    }
    if (node.tagName === "TIME" || (node.tagName === "A" && cls.indexOf("timestamp") !== -1)) return true;
    return false;
  }

  function visibleText(node, stopAtRoot) {
    if (!node) return "";
    if (node.nodeType === 3) return node.textContent || "";
    if (node.nodeType !== 1) return "";
    if (node.tagName === "SCRIPT" || node.tagName === "STYLE") return "";
    if (node.tagName === "BR") return "\n";
    if (isHiddenElement(node) || isChromeNode(node)) return "";
    var parts = [];
    node.childNodes.forEach(function (child) {
      if (stopAtRoot && child === stopAtRoot) return;
      parts.push(visibleText(child, stopAtRoot));
    });
    return parts.join("");
  }

  function ownStableTs(node) {
    if (!node || node.nodeType !== 1) return null;
    return tsFromToken(node.getAttribute("data-ts") || node.getAttribute("data-item-key") || node.id);
  }

  function nestedStableTs(node) {
    var own = ownStableTs(node);
    if (own) return own;
    if (!node || !node.querySelector) return null;
    var stamped = node.querySelector("[data-ts], a.c-timestamp, [id^='message-list']");
    if (stamped) {
      var ts = tsFromToken(stamped.getAttribute("data-ts") || stamped.id);
      if (ts) return ts;
      var permalink = timestampFromPermalink(stamped.getAttribute("href"));
      if (permalink) return permalink;
    }
    var link = node.querySelector('a[href*="/p"]');
    return link ? timestampFromPermalink(link.getAttribute("href")) : null;
  }

  function stableTs(node) {
    return nestedStableTs(node);
  }

  function isKnownWrapper(node) {
    if (!node || node.nodeType !== 1) return false;
    var qa = node.getAttribute("data-qa") || "";
    var virtualItem =
      qa === "virtual-list-item" ||
      qa === "virtual_list_item" ||
      (node.classList && node.classList.contains("c-virtual_list__item"));
    var container = qa === "message_container" || qa === "message-container";
    var kit =
      node.classList &&
      (node.classList.contains("c-message_kit__background") || node.classList.contains("c-message_kit__message"));
    var listId = Boolean(node.id && node.id.indexOf("message-list") === 0 && tsFromToken(node.id));
    var roleMsg = (node.getAttribute("role") || "").toLowerCase() === "message";
    return virtualItem || container || kit || listId || roleMsg;
  }

  function visibleClock(node) {
    if (!node || node.nodeType !== 1) return null;
    var clock = node.querySelector("time[datetime], [datetime], a.c-timestamp, .c-timestamp");
    if (!clock) return null;
    return clock.getAttribute("datetime") || normalizeText(visibleText(clock)) || null;
  }

  function findConversationRoot(doc) {
    return (
      doc.querySelector('[data-qa="message_pane"]') ||
      doc.querySelector(".p-message_pane") ||
      doc.querySelector('[data-qa="slack-conversation"]') ||
      doc.querySelector('[data-qa="page_contents"]') ||
      doc.body
    );
  }

  function findMessagePane(doc) {
    return (
      doc.querySelector('[data-qa="message_pane"]') ||
      doc.querySelector(".p-message_pane") ||
      doc.querySelector('[data-qa="im_browser"], [data-qa="im-browser"]') ||
      doc.querySelector(".p-im_browser") ||
      doc.querySelector(".p-workspace__primary_view") ||
      doc.querySelector('[data-qa="slack-conversation"]') ||
      null
    );
  }

  function findThreadPane(doc) {
    var pane = doc.querySelector('[data-qa="threads_flexpane"]');
    if (!pane) return null;
    if (pane.querySelector('[data-qa="message_container"], [id^="message-list"], .c-message_kit__message, [data-ts]')) {
      return pane;
    }
    return null;
  }

  function parseCurrentUser(root) {
    var search = root && root.querySelector ? root : document;
    var node =
      search.querySelector('[data-qa="current-user"][data-user-id]') ||
      search.querySelector('[data-qa="user-button"][data-user-id]') ||
      search.querySelector('[data-qa="current-user"]') ||
      search.querySelector('[data-qa="user-button"]') ||
      search.querySelector('[data-qa="account-button"][data-user-id]') ||
      search.querySelector('[data-qa="account-button"]');
    if (!node) return { external_id: null, name: null, confidence: "low" };
    var userId = node.getAttribute("data-user-id") || node.getAttribute("data-entity-id") || null;
    var fromAttr = cleanSenderName(node.getAttribute("data-user-name"));
    var fromLabel = cleanSenderName(node.getAttribute("aria-label"));
    var name = fromAttr || fromLabel;
    var confidence = "low";
    if (userId && name) confidence = "high";
    else if (userId) confidence = "high";
    else if (fromAttr) confidence = "medium";
    else confidence = "low";
    return { external_id: userId, name: name, confidence: confidence };
  }

  function isDivider(node) {
    if (!node || node.nodeType !== 1) return false;
    var qa = (node.getAttribute("data-qa") || "").toLowerCase();
    var id = (node.id || "").toLowerCase();
    var className = String(node.className || "").toLowerCase();
    if (qa.indexOf("divider") !== -1 || qa.indexOf("unread") !== -1 || qa.indexOf("start_of_history") !== -1 || qa.indexOf("day_heading") !== -1) {
      return true;
    }
    if (className.indexOf("date_divider") !== -1 || className.indexOf("unread__separator") !== -1 || className.indexOf("c-message_list__day_divider") !== -1) {
      return true;
    }
    if (id.indexOf("date") !== -1 && !tsFromToken(node.id)) return true;
    if (ownStableTs(node) || hasTrustedBody(node)) return false;
    var label = normalizeText(visibleText(node));
    if (DATE_DIVIDER_RE.test(label) || UI_NOISE[label.toLowerCase()]) return true;
    return false;
  }

  function hasTrustedBody(node) {
    if (!node || !node.querySelector) return false;
    for (var i = 0; i < BODY_SELECTORS.length; i += 1) {
      var found = node.querySelector(BODY_SELECTORS[i]);
      if (found && normalizeText(visibleText(found))) return true;
    }
    return false;
  }

  function isCandidateRoot(node) {
    if (!node || node.nodeType !== 1 || isDivider(node) || isChromeNode(node)) return false;
    var wrapper = isKnownWrapper(node);
    var ownTs = ownStableTs(node);
    if (!wrapper && !ownTs) return false;
    if (wrapper && (ownTs || nestedStableTs(node) || hasTrustedBody(node))) return true;
    return Boolean(ownTs && hasTrustedBody(node));
  }

  function containedInKept(node, kept) {
    for (var i = 0; i < kept.length; i += 1) {
      if (kept[i] === node) return true;
      if (kept[i].contains && kept[i].contains(node)) return true;
    }
    return false;
  }

  function collectSelectorMatches(pane, selectors) {
    var found = [];
    var seen = [];
    selectors.forEach(function (selector) {
      if (!pane.querySelectorAll) return;
      Array.prototype.forEach.call(pane.querySelectorAll(selector), function (node) {
        if (seen.indexOf(node) !== -1) return;
        seen.push(node);
        found.push(node);
      });
    });
    return found;
  }

  function sortDocumentOrder(nodes) {
    return nodes.slice().sort(function (a, b) {
      if (a === b) return 0;
      var pos = a.compareDocumentPosition(b);
      if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
      if (pos & Node.DOCUMENT_POSITION_PRECEDING) return 1;
      return 0;
    });
  }

  function findCanonicalMessageRoots(pane) {
    if (!pane) return [];
    var candidates = [];
    collectSelectorMatches(pane, CANDIDATE_SELECTORS).forEach(function (node) {
      if (isCandidateRoot(node)) candidates.push(node);
    });
    if (isCandidateRoot(pane) && candidates.indexOf(pane) === -1) candidates.push(pane);
    var kept = [];
    sortDocumentOrder(candidates).forEach(function (node) {
      if (containedInKept(node, kept)) return;
      kept.push(node);
    });
    return kept;
  }

  function findDividerNodes(pane) {
    if (!pane) return [];
    var found = collectSelectorMatches(pane, DIVIDER_SELECTORS);
    collectSelectorMatches(pane, ['[data-qa="virtual-list-item"]', ".c-virtual_list__item"]).forEach(function (node) {
      if (isDivider(node) && found.indexOf(node) === -1) found.push(node);
    });
    return sortDocumentOrder(found.filter(function (node) {
      return isDivider(node);
    }));
  }

  function findRenderedMessages(root) {
    return findCanonicalMessageRoots(findMessagePane(root) || root);
  }

  function parseSender(node) {
    var sender = node.querySelector(SENDER_SELECTOR);
    if (sender) {
      var name = cleanSenderName(sender.getAttribute("data-user-name") || visibleText(sender));
      var userId = sender.getAttribute("data-user-id") || node.getAttribute("data-user-id") || null;
      return {
        external_id: userId,
        name: name,
        confidence: userId ? "high" : name ? "medium" : "low",
        explicit: true,
      };
    }
    var attrId = node.getAttribute("data-user-id") || node.getAttribute("data-message-sender-id") || null;
    var attrName = cleanSenderName(node.getAttribute("data-user-name"));
    if (attrId || attrName) {
      return { external_id: attrId, name: attrName, confidence: attrId ? "high" : "medium", explicit: true };
    }
    return { external_id: null, name: null, confidence: "low", explicit: false };
  }

  function parseTimestamp(node) {
    return stableTs(node) || visibleClock(node);
  }

  function parseThreadMarker(node, pageUrl, inThreadPane) {
    var threadTs = node.getAttribute("data-thread-ts") || node.getAttribute("data-thread-id");
    var ownTs = nestedStableTs(node);
    if (threadTs && threadTs !== ownTs) return threadTs;
    if (inThreadPane) {
      var urlThread = threadIdFromUrl(pageUrl);
      if (urlThread && urlThread !== ownTs) return urlThread;
    }
    var reply = node.querySelector("[data-thread-ts]");
    if (reply) {
      var marker = reply.getAttribute("data-thread-ts");
      if (marker && marker !== ownTs) return marker;
    }
    return null;
  }

  function isAvatarImage(el) {
    var className = String(el.className || "").toLowerCase();
    var qa = (el.getAttribute("data-qa") || "").toLowerCase();
    var alt = (el.getAttribute("alt") || "").toLowerCase();
    if (className.indexOf("c-avatar") !== -1 || className.indexOf("c-base_icon") !== -1 || className.indexOf("c-presence") !== -1 || className.indexOf("emoji") !== -1) {
      return true;
    }
    if (qa.indexOf("avatar") !== -1 || qa.indexOf("member_image") !== -1 || qa.indexOf("user_image") !== -1 || qa.indexOf("emoji") !== -1) {
      return true;
    }
    if (alt.indexOf("avatar") !== -1 || alt.indexOf("presence") !== -1 || alt.indexOf("emoji") !== -1) return true;
    return false;
  }

  function parseVisibleAttachments(node) {
    if (node.querySelector('[data-qa="image_attachment"], [data-attachment-kind="image"]')) return "image";
    if (node.querySelector('[data-qa="file_attachment"], [data-qa="file_stub"], [data-qa="file_name"]')) return "file";
    var images = node.querySelectorAll("img");
    for (var i = 0; i < images.length; i += 1) {
      if (isAvatarImage(images[i]) || isChromeNode(images[i])) continue;
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

  function parseMessageText(root) {
    var unique = [];
    var seen = {};
    BODY_SELECTORS.forEach(function (selector) {
      Array.prototype.forEach.call(root.querySelectorAll(selector), function (block) {
        if (isChromeNode(block) || isHiddenElement(block)) return;
        var text = normalizeText(visibleText(block));
        if (!text || seen[text]) return;
        seen[text] = true;
        unique.push({ node: block, text: text, depth: depthFrom(root, block) });
      });
    });
    if (!unique.length) return { text: "", selector: null };
    unique.sort(function (a, b) {
      return b.depth - a.depth;
    });
    return { text: unique[0].text, selector: unique[0].node.getAttribute("data-qa") || unique[0].node.className || "body" };
  }

  function depthFrom(root, node) {
    var depth = 0;
    var cur = node;
    while (cur && cur !== root) {
      depth += 1;
      cur = cur.parentNode;
    }
    return depth;
  }

  function parseText(node) {
    return parseMessageText(node).text;
  }

  function directionFor(node, sender, currentUser) {
    var explicit = node.getAttribute("data-from-current-user");
    if (explicit === "true") return "outgoing";
    if (explicit === "false") return "incoming";
    if (node.classList && (node.classList.contains("c-message--me") || String(node.className || "").indexOf("--mine") !== -1)) {
      return "outgoing";
    }
    var currentConfidence = currentUser && currentUser.confidence ? currentUser.confidence : "low";
    if (currentUser && currentUser.external_id && sender.external_id && currentConfidence !== "low") {
      return sender.external_id === currentUser.external_id ? "outgoing" : "incoming";
    }
    if (currentConfidence === "low") return "unknown";
    if (namesMatch(sender.name, currentUser && currentUser.name)) return "outgoing";
    if (sender.name && currentUser && currentUser.name && currentConfidence === "high") return "incoming";
    return "unknown";
  }

  function cleanConversationTitle(value) {
    var name = normalizeText(value);
    name = name.replace(/^\d+\s+/, "");
    name = name.replace(/^direct message with\s+/i, "");
    name = name.replace(/\s+\d+\s+(new|unread).*$/i, "");
    return cleanSenderName(name) || name || null;
  }

  function parseConversation(root, url) {
    var convRoot = findConversationRoot(root);
    var externalId = activeConversationId(root, url);
    if (!externalId) return null;
    var name = (convRoot && convRoot.getAttribute("data-channel-name")) || "";
    var header =
      (convRoot && convRoot.querySelector('[data-qa="channel_name"], [data-qa="channel_name_button"], [data-qa="dm_title"]')) ||
      (root.querySelector && root.querySelector('[data-qa="channel_name_button"], [data-qa="channel_name"], [data-qa="dm_title"]'));
    if (header) name = name || visibleText(header);
    name = cleanConversationTitle(name) || externalId;
    var convType = (convRoot && convRoot.getAttribute("data-channel-type")) || conversationTypeFromId(externalId);
    return {
      external_id: externalId,
      name: name,
      type: convType === "channel" || convType === "direct" || convType === "group" ? convType : "group",
    };
  }

  function messageConfidence(node, ts, text, placeholder, deleted) {
    if (isSlackTs(ts) && (text || placeholder || deleted) && isCandidateRoot(node)) return "high";
    if (isSlackTs(ts)) return "medium";
    if ((text || placeholder) && (parseSender(node).explicit || visibleClock(node))) return "medium";
    return "low";
  }

  function parseMessageNode(node, conversationId, currentUser, pageUrl, options) {
    options = options || {};
    var sender = options.sender || parseSender(node);
    var senderName = cleanSenderName(sender.name);
    var timestamp = parseTimestamp(node) || "";
    var body = parseMessageText(node);
    var text = stripMessageChrome(body.text, senderName);
    var placeholder = parseVisibleAttachments(node);
    var deleted = DELETED_RE.test(text);
    if (deleted) text = "[Deleted Slack message]";
    else if (!text && placeholder === "image") text = "[Image]";
    else if (!text && placeholder === "file") text = "[File]";
    else if (placeholder === "image" && text.indexOf("[Image]") === -1) text = text ? text + "\n[Image]" : "[Image]";
    else if (placeholder === "file" && text.indexOf("[File]") === -1) text = text ? text + "\n[File]" : "[File]";
    if (isNoiseText(text) && !placeholder) return null;
    if (!text && !placeholder) return null;
    var slackId = stableTs(node);
    var confidence = messageConfidence(node, slackId, text, placeholder, deleted);
    if (confidence === "low") return null;
    var browserFallback = false;
    var externalId = slackId;
    if (!externalId) {
      if (confidence !== "medium") return null;
      externalId = fallbackMessageId(conversationId, timestamp, sender.external_id || senderName || "", text);
      browserFallback = true;
    }
    return {
      external_id: externalId,
      sender_external_id: sender.external_id,
      sender_name: senderName,
      timestamp: slackId || timestamp || externalId,
      text: text,
      direction: directionFor(node, sender, currentUser),
      thread_external_id: parseThreadMarker(node, pageUrl, Boolean(options.inThreadPane)),
      browser_fallback_id: browserFallback,
      attachment_placeholder: placeholder,
      deleted: deleted,
      confidence: confidence,
      sender_inherited: Boolean(options.inherited),
      body_selector: body.selector,
      stable_ts: Boolean(slackId),
    };
  }

  function parseRoots(pane, conversationId, currentUser, pageUrl, inThreadPane) {
    var messages = [];
    var lastSender = null;
    var roots = findCanonicalMessageRoots(pane);
    var mixed = roots.concat(findDividerNodes(pane));
    sortDocumentOrder(mixed).forEach(function (node) {
      if (isDivider(node) && roots.indexOf(node) === -1) {
        lastSender = null;
        return;
      }
      if (roots.indexOf(node) === -1) return;
      var explicit = parseSender(node);
      var inherited = false;
      var sender = explicit;
      if (!explicit.explicit && lastSender) {
        sender = lastSender;
        inherited = true;
      } else if (explicit.explicit) {
        lastSender = explicit;
      }
      var parsed = parseMessageNode(node, conversationId, currentUser, pageUrl, {
        sender: sender,
        inherited: inherited,
        inThreadPane: inThreadPane,
      });
      if (parsed) messages.push(parsed);
    });
    return messages;
  }

  function emptyDiagnostics() {
    return {
      candidates: 0,
      canonical_roots: 0,
      parsed: 0,
      skipped_low_confidence: 0,
      stable_ts: 0,
      fallback_ids: 0,
      inherited_sender: 0,
      unknown_direction: 0,
      missing_sender: 0,
      items: [],
    };
  }

  function parseDocument(doc, url) {
    var conversation = parseConversation(doc, url);
    var currentUser = parseCurrentUser(doc);
    var conversationId = (conversation && conversation.external_id) || conversationIdFromUrl(url) || "unknown";
    var mainPane = findMessagePane(doc) || doc.body || doc;
    var threadPane = findThreadPane(doc);
    var diagnostics = emptyDiagnostics();
    var rawCandidates = collectSelectorMatches(mainPane, CANDIDATE_SELECTORS).length;
    if (threadPane) rawCandidates += collectSelectorMatches(threadPane, CANDIDATE_SELECTORS).length;
    var canonical = findCanonicalMessageRoots(mainPane);
    if (threadPane) canonical = canonical.concat(findCanonicalMessageRoots(threadPane));
    diagnostics.candidates = rawCandidates;
    diagnostics.canonical_roots = canonical.length;
    var mainMessages = parseRoots(mainPane, conversationId, currentUser, url, false);
    var threadMessages = threadPane ? parseRoots(threadPane, conversationId, currentUser, url, true) : [];
    var messages = [];
    var seen = {};
    function add(parsed) {
      if (!parsed || seen[parsed.external_id]) return;
      seen[parsed.external_id] = true;
      messages.push(parsed);
      diagnostics.parsed += 1;
      if (parsed.stable_ts) diagnostics.stable_ts += 1;
      if (parsed.browser_fallback_id) diagnostics.fallback_ids += 1;
      if (parsed.sender_inherited) diagnostics.inherited_sender += 1;
      if (parsed.direction === "unknown") diagnostics.unknown_direction += 1;
      if (!parsed.sender_name && !parsed.sender_external_id) diagnostics.missing_sender += 1;
      diagnostics.items.push({
        stable_ts: parsed.stable_ts,
        sender: parsed.sender_inherited ? "inherited" : parsed.sender_external_id || parsed.sender_name ? "explicit" : "missing",
        sender_id_present: Boolean(parsed.sender_external_id),
        body_selector: parsed.body_selector,
        direction: parsed.direction,
        confidence: parsed.confidence,
        fallback: parsed.browser_fallback_id,
      });
    }
    mainMessages.forEach(add);
    threadMessages.forEach(add);
    diagnostics.skipped_low_confidence = Math.max(0, diagnostics.canonical_roots - diagnostics.parsed);
    return {
      conversation: conversation,
      current_user: currentUser,
      messages: messages,
      workspace_present: Boolean(conversation || conversationIdFromUrl(url)),
      diagnostics: diagnostics,
    };
  }

  function semanticFingerprint(message) {
    return [
      message.text || "",
      message.sender_external_id || "",
      message.sender_name || "",
      message.direction || "",
      message.thread_external_id || "",
      message.attachment_placeholder || "",
      message.deleted ? "1" : "0",
    ].join("\u0000");
  }

  function mutationLooksLikeChrome(node) {
    if (!node) return true;
    if (node.nodeType === 3) return mutationLooksLikeChrome(node.parentElement);
    if (node.nodeType !== 1) return true;
    if (isChromeNode(node)) return true;
    var text = normalizeText(node.textContent || "");
    if (/^(add reaction|reply|more actions|save for later|\d+\s*replies?|👍|❤️)$/i.test(text) && !hasTrustedBody(node)) {
      return true;
    }
    return false;
  }

  function isSemanticMutation(mutation, pane) {
    if (!pane) return false;
    var target = mutation.target;
    if (target && pane.contains && !pane.contains(target) && target !== pane) return false;
    if (mutation.type === "characterData") {
      return !mutationLooksLikeChrome(target);
    }
    if (mutation.type !== "childList") return false;
    var nodes = [];
    Array.prototype.forEach.call(mutation.addedNodes || [], function (node) {
      nodes.push(node);
    });
    if (!nodes.length) return false;
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      if (node.nodeType !== 1) continue;
      if (mutationLooksLikeChrome(node)) continue;
      if (isCandidateRoot(node) || hasTrustedBody(node) || (node.querySelector && node.querySelector("[data-ts], [data-qa='message_container']"))) {
        return true;
      }
    }
    return false;
  }

  function sanitizeCurrentSlackDom(doc, url) {
    var pane = findMessagePane(doc) || doc.body;
    var roots = findCanonicalMessageRoots(pane);
    var users = {};
    var userCount = 0;
    var msgCount = 0;
    function userLabel(id, name) {
      var key = id || name || "anon";
      if (!users[key]) {
        userCount += 1;
        users[key] = "User " + String.fromCharCode(64 + Math.min(userCount, 26));
      }
      return users[key];
    }
    var clone = pane.cloneNode(true);
    var walker = clone.querySelectorAll ? clone.querySelectorAll("*") : [];
    Array.prototype.forEach.call(walker, function (el) {
      ["data-user-id", "data-message-sender-id", "data-entity-id"].forEach(function (attr) {
        if (el.getAttribute(attr)) el.setAttribute(attr, "UXXXX");
      });
      ["data-channel-id", "data-item-key"].forEach(function (attr) {
        var value = el.getAttribute(attr);
        if (!value) return;
        if (/^[CDG]/i.test(value)) el.setAttribute(attr, value.charAt(0).toUpperCase() + "XXXX");
      });
      if (el.getAttribute("href")) el.setAttribute("href", "https://example.com");
      if (el.getAttribute("src")) el.setAttribute("src", "https://example.com/file");
    });
    roots.forEach(function () {
      msgCount += 1;
    });
    var html = clone.outerHTML || "";
    html = html.replace(/[CDG][A-Z0-9]{8,}/g, function (match) {
      return match.charAt(0) + "XXXX";
    });
    html = html.replace(/T[A-Z0-9]{8,}/g, "TXXXX");
    html = html.replace(/U[A-Z0-9]{6,}/g, "UXXXX");
    html = html.replace(/https?:\/\/[^\s"'<>]+/g, "https://example.com");
    return {
      conversation_id: conversationIdFromUrl(url),
      canonical_roots: roots.length,
      html: html,
      note: "Sanitized structural HTML. Review before saving a fixture. messages≈" + msgCount,
    };
  }

  root.SlackDomParser = {
    parseDocument: parseDocument,
    findConversationRoot: findConversationRoot,
    findMessagePane: findMessagePane,
    findThreadPane: findThreadPane,
    findDividerNodes: findDividerNodes,
    findCanonicalMessageRoots: findCanonicalMessageRoots,
    findRenderedMessages: findRenderedMessages,
    parseMessageNode: parseMessageNode,
    parseSender: parseSender,
    parseTimestamp: parseTimestamp,
    parseText: parseText,
    parseThreadMarker: parseThreadMarker,
    parseVisibleAttachments: parseVisibleAttachments,
    conversationIdFromUrl: conversationIdFromUrl,
    activeConversationId: activeConversationId,
    fallbackMessageId: fallbackMessageId,
    shaFallback: shaFallback,
    isSlackTs: isSlackTs,
    isDivider: isDivider,
    isChromeNode: isChromeNode,
    isCandidateRoot: isCandidateRoot,
    semanticFingerprint: semanticFingerprint,
    isSemanticMutation: isSemanticMutation,
    sanitizeCurrentSlackDom: sanitizeCurrentSlackDom,
    parseCurrentUser: parseCurrentUser,
  };
})(typeof globalThis !== "undefined" ? globalThis : window);
