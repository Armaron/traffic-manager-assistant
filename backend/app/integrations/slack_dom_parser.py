"""Isolated Slack DOM parser. Selectors live in this module only.

Reads rendered Slack HTML fixtures / a live document's data attributes.
Never reads cookies, localStorage, or Slack credentials.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser

SLACK_TS_RE = re.compile(r"^\d{9,12}\.\d+$")
EMBEDDED_TS_RE = re.compile(r"(\d{9,12}\.\d+)")
CLIENT_CONV_RE = re.compile(r"/client/(?:[ET][A-Z0-9]+/)+([CDG][A-Z0-9]+)", re.IGNORECASE)
CLIENT_CONV_LOOSE_RE = re.compile(r"/client/(?:[^/?#]+/)*([CDG][A-Z0-9]{8,})", re.IGNORECASE)
ARCHIVES_CONV_RE = re.compile(r"/archives/([CDG][A-Z0-9]+)", re.IGNORECASE)
CONV_ID_RE = re.compile(r"^[CDG][A-Z0-9]{6,}$", re.IGNORECASE)
CHANNEL_QUERY_RE = re.compile(r"[?&](?:channel|cid)=([CDG][A-Z0-9]+)", re.IGNORECASE)
THREAD_URL_RE = re.compile(r"/thread/[CDG][A-Z0-9]+-(\d+\.\d+)", re.IGNORECASE)
PERMALINK_TS_RE = re.compile(r"/p(\d{10})(\d+)")
DELETED_RE = re.compile(r"this message was deleted", re.IGNORECASE)
MONTH_RE = (
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"январ[ья]|феврал[ья]|марта?|апрел[ья]|ма[йя]|июн[ья]|июл[ья]|августа?|"
    r"сентябр[ья]|октябр[ья]|ноябр[ья]|декабр[ья]"
)
WEEKDAY_RE = (
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"понедельник|вторник|среда|четверг|пятница|суббота|воскресенье"
)
DATE_DIVIDER_RE = re.compile(
    rf"^(?:today|yesterday|tomorrow|сегодня|вчера|завтра|"
    rf"(?:{WEEKDAY_RE}),?\s+(?:(?:{MONTH_RE})\s+)?\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|"
    rf"(?:{MONTH_RE})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|"
    rf"\d{{1,2}}\s+(?:{MONTH_RE})(?:,?\s+\d{{4}})?|"
    rf"\d{{1,2}}[./-]\d{{1,2}}(?:[./-]\d{{2,4}})?)$",
    re.IGNORECASE,
)
CLOCK_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?\.?\s*", re.IGNORECASE)
TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?\.?$", re.IGNORECASE)
PLACEHOLDER_SENDERS = frozenset(
    {
        "name and last name",
        "full name",
        "display name",
        "unknown",
        "user",
        "member",
    }
)
UI_NOISE = frozenset({"new", "unread", "jump to date", "jump to the most recent"})

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)

CONVERSATION_ROOT_ATTRS = (
    ("data-qa", "slack-conversation"),
    ("data-qa", "page_contents"),
)
MESSAGE_ATTRS = (
    ("data-qa", "message_container"),
    ("data-qa", "virtual-list-item"),
)
CURRENT_USER_ATTRS = (
    ("data-qa", "current-user"),
    ("data-qa", "user-button"),
    ("data-qa", "account-button"),
)
CHROME_QA_PREFIXES = (
    "hover",
    "message_actions",
    "emoji-bar",
    "reaction",
    "save_message",
    "share_message",
    "more_actions",
    "reply_in_thread",
    "reply_bar",
    "thread_replies",
    "bookmark",
    "pin",
    "unread",
    "date_divider",
    "day_heading",
)
SENDER_ATTRS = (
    ("data-qa", "message_sender"),
    ("data-qa", "message_sender_name"),
)
TEXT_ATTRS = (
    ("data-qa", "message-text"),
    ("data-qa", "message_text"),
    ("data-qa", "message_content"),
)
TEXT_CLASSES = ("p-rich_text_section", "c-message_kit__text", "c-message__body")
TIMESTAMP_CLASSES = ("c-timestamp",)
THREAD_PANE_ATTRS = (("data-qa", "threads_flexpane"),)
FILE_ATTRS = (("data-qa", "file_attachment"), ("data-qa", "image_attachment"))


@dataclass(frozen=True)
class DomNode:
    tag: str
    attrs: dict[str, str]
    children: tuple["DomNode", ...]
    text: str

    def iter(self) -> tuple["DomNode", ...]:
        nodes: list[DomNode] = [self]
        for child in self.children:
            nodes.extend(child.iter())
        return tuple(nodes)

    def attr(self, name: str) -> str | None:
        value = self.attrs.get(name)
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    def has_class(self, name: str) -> bool:
        classes = self.attrs.get("class", "").split()
        return name in classes

    def class_contains(self, fragment: str) -> bool:
        return any(fragment in item for item in self.attrs.get("class", "").split())


@dataclass(frozen=True)
class ParsedConversation:
    external_id: str
    name: str
    type: str


@dataclass(frozen=True)
class ParsedIdentity:
    external_id: str | None
    name: str | None
    confidence: str = "low"
    explicit: bool = False


@dataclass(frozen=True)
class ParsedMessage:
    external_id: str
    sender_external_id: str | None
    sender_name: str | None
    timestamp: str
    text: str
    direction: str
    thread_external_id: str | None
    browser_fallback_id: bool
    attachment_placeholder: str | None = None
    deleted: bool = False
    sender_inherited: bool = False


@dataclass(frozen=True)
class ParsedDiagnostics:
    candidates: int = 0
    canonical_roots: int = 0
    parsed: int = 0
    skipped_low_confidence: int = 0
    stable_ts: int = 0
    fallback_ids: int = 0
    inherited_sender: int = 0
    unknown_direction: int = 0
    missing_sender: int = 0


@dataclass(frozen=True)
class ParsedPage:
    conversation: ParsedConversation | None
    current_user: ParsedIdentity
    messages: tuple[ParsedMessage, ...]
    workspace_present: bool
    diagnostics: ParsedDiagnostics = ParsedDiagnostics()


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = DomNode("document", {}, (), "")
        self._stack: list[list[object]] = [["document", {}, [], []]]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        mapping = {key: (value or "") for key, value in attrs if key}
        frame: list[object] = [tag, mapping, [], []]
        if tag in VOID_TAGS:
            self._stack[-1][2].append(frame)  # type: ignore[index]
            return
        self._stack.append(frame)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index][0] == tag:
                frame = self._stack.pop(index)
                if index <= len(self._stack):
                    self._stack[index - 1][2].append(frame)  # type: ignore[index]
                break

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1][3].append(data)  # type: ignore[index]

    def finish(self) -> DomNode:
        while len(self._stack) > 1:
            frame = self._stack.pop()
            self._stack[-1][2].append(frame)  # type: ignore[index]
        return _frame_to_node(self._stack[0])


def _frame_to_node(frame: list[object]) -> DomNode:
    tag = str(frame[0])
    attrs = dict(frame[1])  # type: ignore[arg-type]
    child_nodes = tuple(_frame_to_node(child) for child in frame[2])  # type: ignore[union-attr]
    text = "".join(str(part) for part in frame[3])  # type: ignore[union-attr]
    return DomNode(tag=tag, attrs=attrs, children=child_nodes, text=text)


def parse_html(html: str) -> DomNode:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.finish()


def _is_hidden(node: DomNode) -> bool:
    if node.attr("aria-hidden") == "true" or "hidden" in node.attrs:
        return True
    classes = node.attrs.get("class", "").lower()
    if "offscreen" in classes or "sr-only" in classes or "c-offscreen" in classes:
        return True
    style = node.attrs.get("style") or ""
    if re.search(r"display\s*:\s*none", style, re.IGNORECASE):
        return True
    if re.search(r"visibility\s*:\s*hidden", style, re.IGNORECASE):
        return True
    return False


def _is_chrome_node(node: DomNode) -> bool:
    qa = node.attr("data-qa") or ""
    lowered = qa.lower()
    if any(lowered.startswith(prefix) for prefix in CHROME_QA_PREFIXES):
        return True
    if any(token in lowered for token in ("divider", "unread", "toolbar", "actions")):
        return True
    classes = node.attrs.get("class", "").lower()
    if any(
        token in classes
        for token in (
            "c-message_actions",
            "c-reaction",
            "c-icon_button",
            "c-timestamp",
            "c-message_kit__reactions",
            "c-message_list__day_divider",
            "unread__separator",
        )
    ):
        return True
    if node.tag == "time":
        return True
    if node.tag == "a" and "timestamp" in classes:
        return True
    return False


def _visible_text(node: DomNode) -> str:
    if node.tag in {"script", "style"}:
        return ""
    if _is_hidden(node) or _is_chrome_node(node):
        return ""
    parts: list[str] = []
    if node.text:
        parts.append(node.text)
    for child in node.children:
        if child.tag == "br":
            parts.append("\n")
            continue
        parts.append(_visible_text(child))
    return "".join(parts)


def _normalize_text(value: str) -> str:
    lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
    collapsed = "\n".join(lines)
    collapsed = re.sub(r"[ \t]+", " ", collapsed)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    return collapsed.strip()


def conversation_id_from_url(url: str) -> str | None:
    if not url:
        return None
    match = (
        CLIENT_CONV_RE.search(url)
        or CLIENT_CONV_LOOSE_RE.search(url)
        or ARCHIVES_CONV_RE.search(url)
        or CHANNEL_QUERY_RE.search(url)
    )
    if match and is_conversation_id(match.group(1)):
        return match.group(1)
    return None


def is_conversation_id(value: str | None) -> bool:
    return bool(value and CONV_ID_RE.match(value))


def ts_from_token(value: str | None) -> str | None:
    if not value:
        return None
    if is_slack_ts(value):
        return value
    match = EMBEDDED_TS_RE.search(value)
    return match.group(1) if match else None


def conversation_type_from_id(conversation_id: str) -> str:
    prefix = conversation_id[:1].upper()
    if prefix == "D":
        return "direct"
    if prefix == "C":
        return "channel"
    if prefix == "G":
        return "group"
    return "group"


def thread_id_from_url(url: str) -> str | None:
    match = THREAD_URL_RE.search(url or "")
    return match.group(1) if match else None


def timestamp_from_permalink(href: str | None) -> str | None:
    if not href:
        return None
    match = PERMALINK_TS_RE.search(href)
    if not match:
        return None
    return f"{match.group(1)}.{match.group(2)}"


def is_slack_ts(value: str | None) -> bool:
    return bool(value and SLACK_TS_RE.match(value))


def fallback_message_id(conversation_id: str, timestamp: str, sender: str, text: str) -> str:
    material = f"{conversation_id}\n{timestamp}\n{sender}\n{text}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"b_{digest}"


def _collapsed_name(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def names_match(left: str | None, right: str | None) -> bool:
    a = _normalize_text(left or "")
    b = _normalize_text(right or "")
    if not a or not b:
        return False
    ca = _collapsed_name(a)
    cb = _collapsed_name(b)
    if ca == cb:
        return True
    shorter, longer = (ca, cb) if len(ca) <= len(cb) else (cb, ca)
    if len(shorter) >= 4 and longer.startswith(shorter):
        return True
    words_a = a.lower().split()
    words_b = b.lower().split()
    if words_a and words_b and words_a[0] == words_b[0] and len(words_a[0]) >= 3:
        if len(words_a) == 1 or len(words_b) == 1:
            return True
    return False


def clean_sender_name(value: str | None) -> str | None:
    name = _normalize_text(value or "")
    if not name:
        return None
    name = name.split("\n", 1)[0].strip()
    name = re.sub(r"^(user menu for|account for|logged in as)\s+", "", name, flags=re.IGNORECASE)
    tokens = name.split()
    if tokens:
        matches = list(re.finditer(re.escape(tokens[0]), name, flags=re.IGNORECASE))
        if len(matches) >= 2 and matches[0].start() == 0:
            left = name[: matches[1].start()].strip()
            right = name[matches[1].start() :].strip()
            if names_match(left, right):
                name = left
    half = len(name) // 2
    if half >= 4 and name[:half].lower() == name[half:].lower():
        name = name[:half].strip()
    collapsed = _collapsed_name(name)
    mid = len(collapsed) // 2
    if mid >= 4 and collapsed[:mid] == collapsed[mid:]:
        name = name[: max(1, len(name) // 2)].strip()
    if name.lower() in PLACEHOLDER_SENDERS:
        return None
    return name or None


def strip_message_chrome(text: str, sender_name: str | None = None) -> str:
    cleaned = _normalize_text(text)
    previous = None
    while cleaned and cleaned != previous:
        previous = cleaned
        if sender_name:
            prefix = _normalize_text(sender_name)
            if prefix and cleaned.lower().startswith(prefix.lower()):
                cleaned = cleaned[len(prefix) :].lstrip(" :,-")
                continue
        stripped = CLOCK_RE.sub("", cleaned).lstrip(" :.-")
        if stripped != cleaned:
            cleaned = stripped
            continue
        break
    cleaned = re.sub(r"(?:\d{1,2}:\d{2}(?:\s*[ap]m)?){2,}", "", cleaned, flags=re.IGNORECASE)
    return _normalize_text(cleaned)


def is_noise_text(text: str) -> bool:
    value = _normalize_text(text)
    if not value:
        return True
    if value in {"[Image]", "[File]", "[Deleted Slack message]"}:
        return False
    lowered = value.lower()
    if DATE_DIVIDER_RE.match(value) or lowered in PLACEHOLDER_SENDERS or lowered in UI_NOISE:
        return True
    if TIME_ONLY_RE.match(value):
        return True
    if re.match(
        r"^(add reaction|reply|reply in thread|more actions|save for later|forward|share|edited|\d+\s+replies?)$",
        value,
        re.IGNORECASE,
    ):
        return True
    if CLOCK_RE.match(value) and not re.search(r"[a-zа-яё]", value, re.IGNORECASE):
        return True
    return False


def _find_by_attr(root: DomNode, name: str, value: str) -> DomNode | None:
    for node in root.iter():
        if node.attr(name) == value:
            return node
    return None


def _find_all_by_attr(root: DomNode, name: str, value: str) -> list[DomNode]:
    return [node for node in root.iter() if node.attr(name) == value]


def find_conversation_root(root: DomNode) -> DomNode | None:
    pane = find_message_pane(root)
    if pane is not None:
        return pane
    for attr, value in CONVERSATION_ROOT_ATTRS:
        found = _find_by_attr(root, attr, value)
        if found is not None:
            return found
    return root


def find_message_pane(root: DomNode) -> DomNode | None:
    return (
        _find_by_attr(root, "data-qa", "message_pane")
        or _find_by_class(root, "p-message_pane")
        or _find_by_attr(root, "data-qa", "im_browser")
        or _find_by_attr(root, "data-qa", "im-browser")
        or _find_by_class(root, "p-im_browser")
        or _find_by_class(root, "p-workspace__primary_view")
        or _find_by_attr(root, "data-qa", "slack-conversation")
    )


def _sidebar_roots(root: DomNode) -> list[DomNode]:
    found: list[DomNode] = []
    for node in root.iter():
        qa = (node.attr("data-qa") or "").lower()
        classes = node.attrs.get("class", "").lower()
        if qa in {"channel_sidebar", "user_sidebar"} or "p-channel_sidebar" in classes:
            found.append(node)
    return found


def _conversation_id_from_node(node: DomNode | None) -> str | None:
    if node is None:
        return None
    return next(
        (
            value
            for value in (node.attr("data-channel-id"), node.attr("data-entity-id"))
            if is_conversation_id(value)
        ),
        None,
    )


def _under_any(node: DomNode, ancestors: list[DomNode]) -> bool:
    return any(_is_under(node, ancestor) for ancestor in ancestors)


def _conversation_id_from_hrefs(node: DomNode) -> str | None:
    counts: dict[str, int] = {}
    for child in node.iter():
        found = conversation_id_from_url(child.attr("href") or "")
        if found:
            counts[found] = counts.get(found, 0) + 1
    if not counts:
        return None
    return max(counts, key=counts.get)


def conversation_id_from_active_pane(root: DomNode) -> str | None:
    pane = find_message_pane(root)
    sidebars = _sidebar_roots(root)
    if pane is not None:
        own = _conversation_id_from_node(pane)
        if own:
            return own
        for node in pane.iter():
            if node.attr("data-ts") or _under_any(node, sidebars):
                continue
            found = _conversation_id_from_node(node)
            if found:
                return found
        from_links = _conversation_id_from_hrefs(pane)
        if from_links:
            return from_links
        ancestors = [node for node in root.iter() if node is not pane and _is_under(pane, node)]
        for node in reversed(ancestors):
            if _under_any(node, sidebars):
                continue
            found = _conversation_id_from_node(node)
            if found:
                return found
    for attr, value in (
        ("data-qa", "channel_name_button"),
        ("data-qa", "channel_name"),
        ("data-qa", "dm_title"),
    ):
        header = _find_by_attr(root, attr, value)
        if header is None:
            continue
        href_id = conversation_id_from_url(header.attr("href") or "")
        if href_id:
            return href_id
        for child in header.iter():
            href_id = conversation_id_from_url(child.attr("href") or "")
            if href_id:
                return href_id
    return _conversation_id_from_hrefs(root)


def active_conversation_id(root: DomNode, url: str) -> str | None:
    return conversation_id_from_active_pane(root) or conversation_id_from_url(url)


def find_thread_pane(root: DomNode) -> DomNode | None:
    pane = _find_by_attr(root, "data-qa", "threads_flexpane")
    if pane is None:
        return None
    if any(_is_candidate_root(child) for child in pane.iter()):
        return pane
    return None


def _find_by_class(root: DomNode, name: str) -> DomNode | None:
    for node in root.iter():
        if node.has_class(name):
            return node
    return None


def parse_current_user(root: DomNode) -> ParsedIdentity:
    matches: list[DomNode] = []
    for attr, value in CURRENT_USER_ATTRS:
        matches.extend(_find_all_by_attr(root, attr, value))
    if not matches:
        return ParsedIdentity(external_id=None, name=None, confidence="low")
    matches.sort(key=lambda node: 0 if node.attr("data-user-id") else 1)
    node = matches[0]
    user_id = node.attr("data-user-id") or node.attr("data-entity-id")
    name = clean_sender_name(node.attr("data-user-name") or node.attr("aria-label"))
    if user_id:
        confidence = "high"
    elif node.attr("data-user-name"):
        confidence = "medium"
    else:
        confidence = "low"
    return ParsedIdentity(external_id=user_id, name=name, confidence=confidence)


def _own_stable_ts(node: DomNode) -> str | None:
    return ts_from_token(node.attr("data-ts") or node.attr("data-item-key") or node.attr("id"))


def _nested_stable_ts(node: DomNode) -> str | None:
    own = _own_stable_ts(node)
    if own:
        return own
    for child in node.iter():
        ts = ts_from_token(child.attr("data-ts") or child.attr("id"))
        if ts:
            return ts
        permalink = timestamp_from_permalink(child.attr("href"))
        if permalink:
            return permalink
    return None


def _has_trusted_body(node: DomNode) -> bool:
    for child in node.iter():
        qa = child.attr("data-qa") or ""
        if qa in {"message-text", "message_text", "message_content"} or any(child.has_class(name) for name in TEXT_CLASSES):
            if _normalize_text(_visible_text(child)):
                return True
    return False


def _is_known_wrapper(node: DomNode) -> bool:
    qa = node.attr("data-qa") or ""
    if qa in {"virtual-list-item", "virtual_list_item", "message_container", "message-container"}:
        return True
    if node.has_class("c-virtual_list__item") or node.has_class("c-message_kit__background") or node.has_class(
        "c-message_kit__message"
    ):
        return True
    node_id = node.attr("id") or ""
    if node_id.startswith("message-list") and ts_from_token(node_id):
        return True
    return (node.attr("role") or "").lower() == "message"


def _is_divider(node: DomNode) -> bool:
    qa = (node.attr("data-qa") or "").lower()
    node_id = (node.attr("id") or "").lower()
    classes = node.attrs.get("class", "").lower()
    if "divider" in qa or "unread" in qa or "start_of_history" in qa or "day_heading" in qa:
        if not _has_trusted_body(node) and not _own_stable_ts(node):
            return True
    if "date_divider" in classes or "unread__separator" in classes or "c-message_list__day_divider" in classes:
        return True
    if "date" in node_id and ts_from_token(node.attr("id")) is None and not _has_trusted_body(node):
        return True
    if _own_stable_ts(node) or _has_trusted_body(node):
        return False
    label = _normalize_text(_visible_text(node))
    if DATE_DIVIDER_RE.match(label) or label.lower() in UI_NOISE:
        return True
    return False


def _is_candidate_root(node: DomNode) -> bool:
    if _is_divider(node) or _is_chrome_node(node):
        return False
    wrapper = _is_known_wrapper(node)
    own_ts = _own_stable_ts(node)
    if not wrapper and not own_ts:
        return False
    if wrapper and (own_ts or _nested_stable_ts(node) or _has_trusted_body(node)):
        return True
    return bool(own_ts and _has_trusted_body(node))


def _is_under(node: DomNode, ancestor: DomNode) -> bool:
    if node is ancestor:
        return True
    for child in ancestor.iter():
        if child is node:
            return True
    return False


def find_canonical_message_roots(pane: DomNode) -> list[DomNode]:
    candidates = [node for node in pane.iter() if _is_candidate_root(node)]
    kept: list[DomNode] = []
    for node in candidates:
        if any(_is_under(node, parent) for parent in kept):
            continue
        kept.append(node)
    return kept


def find_divider_nodes(pane: DomNode) -> list[DomNode]:
    return [node for node in pane.iter() if _is_divider(node) and not _is_candidate_root(node)]


def find_rendered_messages(root: DomNode) -> list[DomNode]:
    pane = find_thread_pane(root) or find_message_pane(root) or root
    return find_canonical_message_roots(pane)


def parse_sender(node: DomNode) -> ParsedIdentity:
    for attr, value in SENDER_ATTRS:
        sender = _find_by_attr(node, attr, value)
        if sender is not None:
            user_id = sender.attr("data-user-id") or node.attr("data-user-id")
            name = clean_sender_name(sender.attr("data-user-name") or _normalize_text(_visible_text(sender)))
            return ParsedIdentity(
                external_id=user_id,
                name=name or None,
                confidence="high" if user_id else "medium" if name else "low",
                explicit=True,
            )
    user_id = node.attr("data-user-id") or node.attr("data-message-sender-id")
    name = node.attr("data-user-name")
    for child in node.iter():
        if child.has_class("c-message__sender_button") or child.has_class("c-message_kit__sender") or child.has_class(
            "c-message__sender"
        ):
            parsed_name = clean_sender_name(_normalize_text(_visible_text(child)) or name)
            child_id = child.attr("data-user-id") or user_id
            return ParsedIdentity(
                external_id=child_id,
                name=parsed_name,
                confidence="high" if child_id else "medium" if parsed_name else "low",
                explicit=True,
            )
    if user_id or name:
        cleaned = clean_sender_name(name)
        return ParsedIdentity(
            external_id=user_id,
            name=cleaned,
            confidence="high" if user_id else "medium",
            explicit=True,
        )
    return ParsedIdentity(external_id=None, name=None, confidence="low", explicit=False)


def parse_timestamp(node: DomNode) -> str | None:
    nested = _nested_stable_ts(node)
    if nested:
        return nested
    for child in node.iter():
        datetime_attr = child.attr("datetime")
        if datetime_attr:
            return datetime_attr
        if child.has_class("c-timestamp") or child.tag == "time":
            clock = _normalize_text(child.text)
            if clock:
                return clock
    return None


def parse_thread_marker(node: DomNode, page_url: str, in_thread_pane: bool = False) -> str | None:
    thread_ts = node.attr("data-thread-ts") or node.attr("data-thread-id")
    own_ts = _nested_stable_ts(node)
    if thread_ts and thread_ts != own_ts:
        return thread_ts
    if in_thread_pane:
        url_thread = thread_id_from_url(page_url)
        if url_thread and url_thread != own_ts:
            return url_thread
    for child in node.iter():
        marker = child.attr("data-thread-ts")
        if marker and marker != own_ts:
            return marker
    return None


def _is_avatar_image(node: DomNode) -> bool:
    classes = node.attrs.get("class", "").lower()
    qa = (node.attr("data-qa") or "").lower()
    alt = (node.attr("alt") or "").lower()
    if any(hint in classes for hint in ("c-avatar", "c-base_icon", "c-presence", "emoji")):
        return True
    if "avatar" in qa or "member_image" in qa or "user_image" in qa or "emoji" in qa:
        return True
    if "avatar" in alt or "presence" in alt or "emoji" in alt:
        return True
    return False


def parse_visible_attachments(node: DomNode) -> str | None:
    for attr, value in FILE_ATTRS:
        attachment = _find_by_attr(node, attr, value)
        if attachment is None:
            continue
        kind = attachment.attr("data-attachment-kind") or value
        if "image" in kind:
            return "image"
        return "file"
    for child in node.iter():
        qa = child.attr("data-qa") or ""
        if "file_stub" in qa or qa == "file_name":
            return "file"
        if child.tag != "img" or _is_avatar_image(child):
            continue
        alt = (child.attr("alt") or "").lower()
        src = child.attr("src") or ""
        classes = child.attrs.get("class", "").lower()
        if "file thumbnail" in alt or "image attachment" in alt or "uploaded" in alt:
            return "image"
        if "c-pillow_file" in classes or "p-file_image" in classes or "file_preview" in classes:
            return "image"
        if "files.slack.com" in src.lower() or "slack-files.com" in src.lower() or "files-origin.slack.com" in src.lower():
            return "image"
    return None


def parse_text(node: DomNode) -> str:
    matches: list[DomNode] = []
    for child in node.iter():
        if child is node or _is_hidden(child) or _is_chrome_node(child):
            continue
        qa = child.attr("data-qa") or ""
        if qa in {"message-text", "message_text", "message_content"} or any(child.has_class(name) for name in TEXT_CLASSES):
            matches.append(child)
    innermost = [
        candidate
        for candidate in matches
        if not any(other is not candidate and _is_under(other, candidate) for other in matches)
    ]
    seen: set[str] = set()
    texts: list[str] = []
    for block in innermost:
        text = _normalize_text(_visible_text(block))
        if not text or text in seen:
            continue
        seen.add(text)
        texts.append(text)
    return texts[0] if texts else ""


def _direction_for(node: DomNode, sender: ParsedIdentity, current_user: ParsedIdentity) -> str:
    explicit = node.attr("data-from-current-user")
    if explicit == "true":
        return "outgoing"
    if explicit == "false":
        return "incoming"
    if node.class_contains("--mine") or node.has_class("c-message--me"):
        return "outgoing"
    current_confidence = current_user.confidence or "low"
    if current_user.external_id and sender.external_id and current_confidence != "low":
        if sender.external_id == current_user.external_id:
            return "outgoing"
        return "incoming"
    if current_confidence == "low":
        return "unknown"
    if names_match(sender.name, current_user.name):
        return "outgoing"
    if sender.name and current_user.name and current_confidence == "high":
        return "incoming"
    return "unknown"


def _message_confidence(node: DomNode, slack_id: str | None, text: str, placeholder: str | None, deleted: bool) -> str:
    if is_slack_ts(slack_id) and (text or placeholder or deleted) and _is_candidate_root(node):
        return "high"
    if is_slack_ts(slack_id):
        return "medium"
    if (text or placeholder) and (parse_sender(node).explicit or parse_timestamp(node)):
        return "medium"
    return "low"


def parse_message_node(
    node: DomNode,
    *,
    conversation_id: str,
    current_user: ParsedIdentity,
    page_url: str,
    sender: ParsedIdentity | None = None,
    in_thread_pane: bool = False,
    inherited: bool = False,
) -> ParsedMessage | None:
    resolved_sender = sender or parse_sender(node)
    sender_name = clean_sender_name(resolved_sender.name)
    timestamp = parse_timestamp(node) or ""
    text = strip_message_chrome(parse_text(node), sender_name)
    placeholder = parse_visible_attachments(node)
    deleted = bool(DELETED_RE.search(text))
    if deleted:
        text = "[Deleted Slack message]"
    elif not text and placeholder == "image":
        text = "[Image]"
    elif not text and placeholder == "file":
        text = "[File]"
    elif placeholder == "image" and "[Image]" not in text:
        text = f"{text}\n[Image]".strip() if text else "[Image]"
    elif placeholder == "file" and "[File]" not in text:
        text = f"{text}\n[File]".strip() if text else "[File]"
    if is_noise_text(text) and placeholder is None:
        return None
    if not text and not placeholder:
        return None
    slack_id = _nested_stable_ts(node)
    confidence = _message_confidence(node, slack_id, text, placeholder, deleted)
    if confidence == "low":
        return None
    browser_fallback = False
    if slack_id:
        external_id = slack_id
    else:
        if confidence != "medium":
            return None
        external_id = fallback_message_id(
            conversation_id,
            timestamp,
            resolved_sender.external_id or sender_name or "",
            text,
        )
        browser_fallback = True
    return ParsedMessage(
        external_id=external_id,
        sender_external_id=resolved_sender.external_id,
        sender_name=sender_name,
        timestamp=slack_id or timestamp or external_id,
        text=text,
        direction=_direction_for(node, resolved_sender, current_user),
        thread_external_id=parse_thread_marker(node, page_url, in_thread_pane),
        browser_fallback_id=browser_fallback,
        attachment_placeholder=placeholder,
        deleted=deleted,
        sender_inherited=inherited,
    )


def clean_conversation_title(value: str | None) -> str | None:
    name = _normalize_text(value or "")
    name = re.sub(r"^\d+\s+", "", name)
    name = re.sub(r"^direct message with\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\d+\s+(new|unread).*$", "", name, flags=re.IGNORECASE)
    return clean_sender_name(name) or name or None


def parse_conversation(root: DomNode, url: str) -> ParsedConversation | None:
    conv_root = find_conversation_root(root)
    external_id = active_conversation_id(root, url)
    if not external_id:
        return None
    name = ""
    if conv_root is not None:
        name = conv_root.attr("data-channel-name") or ""
        header = (
            _find_by_attr(conv_root, "data-qa", "channel_name")
            or _find_by_attr(conv_root, "data-qa", "channel_name_button")
            or _find_by_attr(conv_root, "data-qa", "dm_title")
        )
        if header is None:
            header = (
                _find_by_attr(root, "data-qa", "channel_name_button")
                or _find_by_attr(root, "data-qa", "channel_name")
                or _find_by_attr(root, "data-qa", "dm_title")
            )
        if header is not None:
            name = name or _normalize_text(_visible_text(header))
    name = clean_conversation_title(name) or external_id
    conv_type = conv_root.attr("data-channel-type") if conv_root else None
    return ParsedConversation(
        external_id=external_id,
        name=name,
        type=conv_type or conversation_type_from_id(external_id),
    )


def semantic_fingerprint(message: ParsedMessage) -> str:
    return "\0".join(
        [
            message.text or "",
            message.sender_external_id or "",
            message.sender_name or "",
            message.direction or "",
            message.thread_external_id or "",
            message.attachment_placeholder or "",
            "1" if message.deleted else "0",
        ]
    )


def _parse_pane(
    pane: DomNode,
    *,
    conversation_id: str,
    current_user: ParsedIdentity,
    page_url: str,
    in_thread_pane: bool,
) -> list[ParsedMessage]:
    messages: list[ParsedMessage] = []
    last_sender: ParsedIdentity | None = None
    roots = find_canonical_message_roots(pane)
    mixed = roots + [node for node in find_divider_nodes(pane) if node not in roots]
    ordered: list[DomNode] = []
    seen_nodes: set[int] = set()
    for node in pane.iter():
        if node in mixed and id(node) not in seen_nodes:
            seen_nodes.add(id(node))
            ordered.append(node)
    for node in ordered:
        if node not in roots:
            last_sender = None
            continue
        explicit = parse_sender(node)
        inherited = False
        sender = explicit
        if not explicit.explicit and last_sender is not None:
            sender = last_sender
            inherited = True
        elif explicit.explicit:
            last_sender = explicit
        parsed = parse_message_node(
            node,
            conversation_id=conversation_id,
            current_user=current_user,
            page_url=page_url,
            sender=sender,
            in_thread_pane=in_thread_pane,
            inherited=inherited,
        )
        if parsed is None:
            continue
        messages.append(parsed)
    return messages


def parse_slack_dom(html: str, url: str = "") -> ParsedPage:
    """Parse sanitized Slack HTML. DOM node removal is ignored: only present nodes are returned."""
    root = parse_html(html)
    conversation = parse_conversation(root, url)
    current_user = parse_current_user(root)
    conversation_id = conversation.external_id if conversation else conversation_id_from_url(url) or "unknown"
    main_pane = find_message_pane(root) or root
    thread_pane = find_thread_pane(root)
    raw_candidates = sum(1 for node in main_pane.iter() if _is_known_wrapper(node) or _own_stable_ts(node))
    if thread_pane is not None:
        raw_candidates += sum(1 for node in thread_pane.iter() if _is_known_wrapper(node) or _own_stable_ts(node))
    canonical = find_canonical_message_roots(main_pane)
    if thread_pane is not None:
        canonical = canonical + find_canonical_message_roots(thread_pane)
    messages: list[ParsedMessage] = []
    seen_ids: set[str] = set()
    inherited_sender = sum(1 for item in messages if item.sender_inherited)
    for parsed in _parse_pane(
        main_pane,
        conversation_id=conversation_id,
        current_user=current_user,
        page_url=url,
        in_thread_pane=False,
    ) + (
        _parse_pane(
            thread_pane,
            conversation_id=conversation_id,
            current_user=current_user,
            page_url=url,
            in_thread_pane=True,
        )
        if thread_pane is not None
        else []
    ):
        if parsed.external_id in seen_ids:
            continue
        seen_ids.add(parsed.external_id)
        messages.append(parsed)
    diagnostics = ParsedDiagnostics(
        candidates=raw_candidates,
        canonical_roots=len(canonical),
        parsed=len(messages),
        skipped_low_confidence=max(0, len(canonical) - len(messages)),
        stable_ts=sum(1 for item in messages if not item.browser_fallback_id),
        fallback_ids=sum(1 for item in messages if item.browser_fallback_id),
        inherited_sender=inherited_sender,
        unknown_direction=sum(1 for item in messages if item.direction == "unknown"),
        missing_sender=sum(1 for item in messages if not item.sender_name and not item.sender_external_id),
    )
    workspace_present = conversation is not None or bool(conversation_id_from_url(url))
    return ParsedPage(
        conversation=conversation,
        current_user=current_user,
        messages=tuple(messages),
        workspace_present=workspace_present,
        diagnostics=diagnostics,
    )
