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
ARCHIVES_CONV_RE = re.compile(r"/archives/([CDG][A-Z0-9]+)", re.IGNORECASE)
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
    ("data-qa", "account-switcher-button"),
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


@dataclass(frozen=True)
class ParsedPage:
    conversation: ParsedConversation | None
    current_user: ParsedIdentity
    messages: tuple[ParsedMessage, ...]
    workspace_present: bool


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


def _visible_text(node: DomNode) -> str:
    if node.tag in {"script", "style"}:
        return ""
    if node.attr("aria-hidden") == "true":
        return ""
    if node.has_class("offscreen") or node.class_contains("offscreen"):
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
    match = CLIENT_CONV_RE.search(url) or ARCHIVES_CONV_RE.search(url) or CHANNEL_QUERY_RE.search(url)
    if match:
        return match.group(1)
    return None


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
    for attr, value in CONVERSATION_ROOT_ATTRS:
        found = _find_by_attr(root, attr, value)
        if found is not None:
            return found
    for node in root.iter():
        if node.attr("data-channel-id"):
            return node
    return root


def parse_current_user(root: DomNode) -> ParsedIdentity:
    for attr, value in CURRENT_USER_ATTRS:
        node = _find_by_attr(root, attr, value)
        if node is None:
            continue
        user_id = node.attr("data-user-id") or node.attr("data-entity-id")
        name = clean_sender_name(
            node.attr("data-user-name") or node.attr("aria-label") or _visible_text(node)
        )
        return ParsedIdentity(external_id=user_id, name=name)
    return ParsedIdentity(external_id=None, name=None)


def _is_divider(node: DomNode) -> bool:
    qa = (node.attr("data-qa") or "").lower()
    node_id = (node.attr("id") or "").lower()
    classes = node.attrs.get("class", "").lower()
    if "divider" in qa or "unread" in qa or "start_of_history" in qa or "day_heading" in qa:
        return True
    if "date_divider" in classes or "unread__separator" in classes or "c-message_list__day_divider" in classes:
        return True
    if "date" in node_id and ts_from_token(node.attr("id")) is None:
        return True
    label = _normalize_text(_visible_text(node))
    if DATE_DIVIDER_RE.match(label) and not _has_message_signal(node):
        return True
    return False


def _has_message_signal(node: DomNode) -> bool:
    if is_slack_ts(ts_from_token(node.attr("data-ts") or node.attr("data-item-key") or node.attr("id"))):
        return True
    if (node.attr("role") or "").lower() == "message":
        return True
    if (node.attr("data-qa") or "") in {"message_container", "message-container"}:
        return True
    for child in node.iter():
        if child is node:
            continue
        qa = child.attr("data-qa") or ""
        if qa in {"message_container", "message-container", "message-text", "message_text", "message_content"}:
            return True
        if (child.attr("role") or "").lower() == "message":
            return True
        if child.has_class("c-timestamp") or child.has_class("c-message_kit__message") or child.has_class(
            "p-rich_text_section"
        ):
            return True
        if child.tag == "a" and "timestamp" in (child.attrs.get("class") or ""):
            return True
        if ts_from_token(child.attr("data-ts") or child.attr("id")):
            return True
    return False


def _looks_like_message(node: DomNode) -> bool:
    if _is_divider(node):
        return False
    qa = node.attr("data-qa") or ""
    if qa in {"virtual-list-item", "virtual_list_item"}:
        return _has_message_signal(node)
    if qa in {"message_container", "message-container"}:
        return True
    if (node.attr("role") or "").lower() == "message":
        return True
    if (node.attr("id") or "").startswith("message-list") and ts_from_token(node.attr("id")):
        return True
    if node.has_class("c-message_kit__background") or node.has_class("c-message_kit__message"):
        return True
    if node.has_class("c-virtual_list__item") and ts_from_token(node.attr("data-item-key") or node.attr("id")):
        return True
    return bool(ts_from_token(node.attr("data-ts") or node.attr("data-item-key")))


def find_rendered_messages(root: DomNode) -> list[DomNode]:
    pane = None
    thread = _find_by_attr(root, "data-qa", "threads_flexpane")
    if thread is not None:
        has_msgs = any(_looks_like_message(child) for child in thread.iter())
        if has_msgs:
            pane = thread
    if pane is None:
        pane = _find_by_attr(root, "data-qa", "message_pane")
    search_root = pane or root
    found: list[DomNode] = []
    seen: set[int] = set()

    def add(node: DomNode) -> None:
        marker = id(node)
        if marker in seen or not _looks_like_message(node):
            return
        seen.add(marker)
        found.append(node)

    for attr, value in MESSAGE_ATTRS + (("data-qa", "message-container"), ("data-qa", "virtual_list_item")):
        for node in _find_all_by_attr(search_root, attr, value):
            add(node)
    if found:
        return found
    for node in search_root.iter():
        add(node)
    return found


def parse_sender(node: DomNode) -> ParsedIdentity:
    for attr, value in SENDER_ATTRS:
        sender = _find_by_attr(node, attr, value)
        if sender is not None:
            user_id = sender.attr("data-user-id") or node.attr("data-user-id")
            name = clean_sender_name(_normalize_text(_visible_text(sender)) or sender.attr("data-user-name"))
            return ParsedIdentity(external_id=user_id, name=name or None)
    user_id = node.attr("data-user-id") or node.attr("data-message-sender-id")
    name = node.attr("data-user-name")
    for child in node.iter():
        if child.has_class("c-message__sender_button") or child.has_class("c-message_kit__sender") or child.has_class("c-message__sender"):
            return ParsedIdentity(
                external_id=child.attr("data-user-id") or user_id,
                name=clean_sender_name(_normalize_text(_visible_text(child)) or name),
            )
    return ParsedIdentity(external_id=user_id, name=clean_sender_name(name))


def parse_timestamp(node: DomNode) -> str | None:
    direct = ts_from_token(node.attr("data-ts") or node.attr("data-item-key") or node.attr("id"))
    if direct:
        return direct
    for child in node.iter():
        ts = ts_from_token(child.attr("data-ts") or child.attr("id"))
        if ts:
            return ts
        href = child.attr("href")
        permalink_ts = timestamp_from_permalink(href)
        if permalink_ts:
            return permalink_ts
        datetime_attr = child.attr("datetime")
        if datetime_attr:
            return datetime_attr
    return None


def parse_thread_marker(node: DomNode, page_url: str) -> str | None:
    thread_ts = node.attr("data-thread-ts") or node.attr("data-thread-id")
    own_ts = node.attr("data-ts")
    if thread_ts and thread_ts != own_ts:
        return thread_ts
    url_thread = thread_id_from_url(page_url)
    if url_thread and url_thread != own_ts:
        return url_thread
    for child in node.iter():
        label = _normalize_text(_visible_text(child)).lower()
        if child.attr("data-qa") in {"reply_bar", "thread_reply"} or "reply" in (child.attr("data-qa") or ""):
            marker = child.attr("data-thread-ts")
            if marker:
                return marker
        if "replies" in label and child.attr("data-thread-ts"):
            return child.attr("data-thread-ts")
    return None


def _is_avatar_image(node: DomNode) -> bool:
    classes = node.attrs.get("class", "").lower()
    qa = (node.attr("data-qa") or "").lower()
    alt = (node.attr("alt") or "").lower()
    if any(hint in classes for hint in ("c-avatar", "c-base_icon", "c-presence")):
        return True
    if "avatar" in qa or "member_image" in qa or "user_image" in qa:
        return True
    if "avatar" in alt or "presence" in alt:
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
    for child in node.iter():
        qa = child.attr("data-qa") or ""
        if qa in {"message-text", "message_text"} or any(child.has_class(name) for name in TEXT_CLASSES):
            text = _normalize_text(_visible_text(child))
            if text:
                return text
    for attr, value in TEXT_ATTRS:
        block = _find_by_attr(node, attr, value)
        if block is not None:
            text = _normalize_text(_visible_text(block))
            if text:
                return text
    parts: list[str] = []
    for child in node.children:
        qa = child.attr("data-qa") or ""
        if qa in {"message_sender", "message_sender_name", "image_attachment", "file_attachment", "file_stub", "file_name"}:
            continue
        if child.has_class("c-timestamp") or child.has_class("c-message__sender_button") or child.has_class("c-message__sender"):
            continue
        if child.tag in {"time", "a"} and child.attr("data-ts"):
            continue
        if child.tag == "img":
            continue
        parts.append(_visible_text(child))
    return _normalize_text("".join(parts))


def _direction_for(node: DomNode, sender: ParsedIdentity, current_user: ParsedIdentity) -> str:
    explicit = node.attr("data-from-current-user")
    if explicit == "true":
        return "outgoing"
    if explicit == "false":
        return "incoming"
    if node.class_contains("--mine") or node.has_class("c-message--me"):
        return "outgoing"
    if current_user.external_id and sender.external_id:
        if sender.external_id == current_user.external_id:
            return "outgoing"
        return "incoming"
    if names_match(sender.name, current_user.name):
        return "outgoing"
    if clean_sender_name(sender.name) and clean_sender_name(current_user.name):
        return "incoming"
    return "unknown"


def parse_message_node(
    node: DomNode,
    *,
    conversation_id: str,
    current_user: ParsedIdentity,
    page_url: str,
) -> ParsedMessage | None:
    sender = parse_sender(node)
    sender_name = clean_sender_name(sender.name)
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
    slack_id = ts_from_token(node.attr("data-ts") or node.attr("data-item-key") or node.attr("id"))
    if not slack_id:
        slack_id = timestamp if is_slack_ts(timestamp) else None
    browser_fallback = False
    if slack_id:
        external_id = slack_id
    else:
        external_id = fallback_message_id(
            conversation_id,
            timestamp,
            sender.external_id or sender_name or "",
            text,
        )
        browser_fallback = True
    return ParsedMessage(
        external_id=external_id,
        sender_external_id=sender.external_id,
        sender_name=sender_name,
        timestamp=timestamp or external_id,
        text=text,
        direction=_direction_for(node, sender, current_user),
        thread_external_id=parse_thread_marker(node, page_url),
        browser_fallback_id=browser_fallback,
        attachment_placeholder=placeholder,
        deleted=deleted,
    )


def parse_conversation(root: DomNode, url: str) -> ParsedConversation | None:
    conv_root = find_conversation_root(root)
    url_id = conversation_id_from_url(url)
    attr_id = conv_root.attr("data-channel-id") if conv_root else None
    external_id = attr_id or url_id
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
        if header is not None:
            name = name or _normalize_text(_visible_text(header))
    conv_type = conv_root.attr("data-channel-type") if conv_root else None
    return ParsedConversation(
        external_id=external_id,
        name=name or external_id,
        type=conv_type or conversation_type_from_id(external_id),
    )


def parse_slack_dom(html: str, url: str = "") -> ParsedPage:
    """Parse sanitized Slack HTML. DOM node removal is ignored: only present nodes are returned."""
    root = parse_html(html)
    conversation = parse_conversation(root, url)
    current_user = parse_current_user(root)
    conversation_id = conversation.external_id if conversation else conversation_id_from_url(url) or "unknown"
    messages: list[ParsedMessage] = []
    seen_ids: set[str] = set()
    search_root = root
    for node in find_rendered_messages(search_root):
        parsed = parse_message_node(
            node,
            conversation_id=conversation_id,
            current_user=current_user,
            page_url=url,
        )
        if parsed is None:
            continue
        if parsed.external_id in seen_ids:
            continue
        seen_ids.add(parsed.external_id)
        messages.append(parsed)
    workspace_present = conversation is not None or bool(conversation_id_from_url(url))
    return ParsedPage(
        conversation=conversation,
        current_user=current_user,
        messages=tuple(messages),
        workspace_present=workspace_present,
    )
