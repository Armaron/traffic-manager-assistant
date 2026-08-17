from dataclasses import dataclass
from datetime import datetime, timedelta

from app.enums import ChatType, ConversationStatus, Platform
from app.schemas.unified import UnifiedChat, UnifiedMessage, UnifiedSender
from app.time_utils import utc_now


@dataclass(frozen=True)
class MockConversation:
    chat: UnifiedChat
    messages: list[UnifiedMessage]
    demo_status: ConversationStatus


def _msg(
    *,
    platform: Platform,
    chat_id: str,
    chat_name: str,
    external_id: str,
    text: str,
    timestamp: datetime,
    sender_id: str,
    sender_name: str,
    is_outgoing: bool = False,
) -> UnifiedMessage:
    return UnifiedMessage(
        platform=platform,
        external_id=external_id,
        chat_id=chat_id,
        chat_name=chat_name,
        sender_id=sender_id,
        sender_name=sender_name,
        text=text,
        timestamp=timestamp,
        is_outgoing=is_outgoing,
    )


def build_mock_conversations(now: datetime | None = None) -> list[MockConversation]:
    """Deterministic mock inbox used by all mock adapters."""
    current = now or utc_now()

    john_chat = UnifiedChat(
        platform=Platform.TYPEX,
        external_id="typex-affiliate-john",
        name="Affiliate John",
        chat_type=ChatType.DIRECT,
    )
    internal_chat = UnifiedChat(
        platform=Platform.TYPEX,
        external_id="typex-internal-launch",
        name="Internal",
        chat_type=ChatType.GROUP,
    )
    fyi_chat = UnifiedChat(
        platform=Platform.TYPEX,
        external_id="typex-fyi-indonesia-pwa",
        name="FYI — Indonesia PWA",
        chat_type=ChatType.CHANNEL,
    )
    jackie_chat = UnifiedChat(
        platform=Platform.SLACK,
        external_id="slack-jacqueline",
        name="Jacqueline",
        chat_type=ChatType.DIRECT,
    )
    eduard_chat = UnifiedChat(
        platform=Platform.TELEGRAM,
        external_id="telegram-reacheffect-eduard",
        name="ReachEffect — Eduard",
        chat_type=ChatType.DIRECT,
    )

    return [
        MockConversation(
            chat=john_chat,
            demo_status=ConversationStatus.WAITING,
            messages=[
                _msg(
                    platform=Platform.TYPEX,
                    chat_id=john_chat.external_id,
                    chat_name=john_chat.name,
                    external_id="typex-john-1",
                    sender_id="typex-user-john",
                    sender_name="John",
                    text="We've started traffic today.",
                    timestamp=current - timedelta(hours=26),
                ),
                _msg(
                    platform=Platform.TYPEX,
                    chat_id=john_chat.external_id,
                    chat_name=john_chat.name,
                    external_id="typex-john-2",
                    sender_id="typex-user-john",
                    sender_name="John",
                    text="I will send the first stats tomorrow.",
                    timestamp=current - timedelta(hours=25),
                ),
            ],
        ),
        MockConversation(
            chat=internal_chat,
            demo_status=ConversationStatus.NEW,
            messages=[
                _msg(
                    platform=Platform.TYPEX,
                    chat_id=internal_chat.external_id,
                    chat_name=internal_chat.name,
                    external_id="typex-internal-1",
                    sender_id="typex-user-anna",
                    sender_name="Anna",
                    text="Please send me the list of affiliates proposed for launch.",
                    timestamp=current - timedelta(hours=4),
                ),
                _msg(
                    platform=Platform.TYPEX,
                    chat_id=internal_chat.external_id,
                    chat_name=internal_chat.name,
                    external_id="typex-internal-2",
                    sender_id="typex-user-igor",
                    sender_name="Igor",
                    text="I'll send the list today.",
                    timestamp=current - timedelta(hours=3, minutes=40),
                    is_outgoing=True,
                ),
            ],
        ),
        MockConversation(
            chat=fyi_chat,
            demo_status=ConversationStatus.REVIEWED,
            messages=[
                _msg(
                    platform=Platform.TYPEX,
                    chat_id=fyi_chat.external_id,
                    chat_name=fyi_chat.name,
                    external_id="typex-fyi-1",
                    sender_id="typex-user-alex",
                    sender_name="Alex",
                    text="FYI: Indonesia PWA volume looks stable this week.",
                    timestamp=current - timedelta(days=2, hours=2),
                ),
                _msg(
                    platform=Platform.TYPEX,
                    chat_id=fyi_chat.external_id,
                    chat_name=fyi_chat.name,
                    external_id="typex-fyi-2",
                    sender_id="typex-user-alex",
                    sender_name="Alex",
                    text="No action needed from our side.",
                    timestamp=current - timedelta(days=2, hours=1),
                ),
            ],
        ),
        MockConversation(
            chat=jackie_chat,
            demo_status=ConversationStatus.NEEDS_REPLY,
            messages=[
                _msg(
                    platform=Platform.SLACK,
                    chat_id=jackie_chat.external_id,
                    chat_name=jackie_chat.name,
                    external_id="slack-jackie-1",
                    sender_id="slack-user-jacqueline",
                    sender_name="Jacqueline",
                    text="Hi Igor",
                    timestamp=current - timedelta(minutes=28),
                ),
                _msg(
                    platform=Platform.SLACK,
                    chat_id=jackie_chat.external_id,
                    chat_name=jackie_chat.name,
                    external_id="slack-jackie-2",
                    sender_id="slack-user-jacqueline",
                    sender_name="Jacqueline",
                    text="I have a trusted affiliate who wants to promote us.",
                    timestamp=current - timedelta(minutes=22),
                ),
                _msg(
                    platform=Platform.SLACK,
                    chat_id=jackie_chat.external_id,
                    chat_name=jackie_chat.name,
                    external_id="slack-jackie-3",
                    sender_id="slack-user-jacqueline",
                    sender_name="Jacqueline",
                    text="What's the current welcome offer?",
                    timestamp=current - timedelta(minutes=8),
                ),
                _msg(
                    platform=Platform.SLACK,
                    chat_id=jackie_chat.external_id,
                    chat_name=jackie_chat.name,
                    external_id="slack-jackie-4",
                    sender_id="slack-user-jacqueline",
                    sender_name="Jacqueline",
                    text="Any promo for newly signed affiliates?",
                    timestamp=current - timedelta(minutes=5),
                ),
            ],
        ),
        MockConversation(
            chat=eduard_chat,
            demo_status=ConversationStatus.NEEDS_IGOR,
            messages=[
                _msg(
                    platform=Platform.TELEGRAM,
                    chat_id=eduard_chat.external_id,
                    chat_name=eduard_chat.name,
                    external_id="tg-eduard-1",
                    sender_id="tg-user-eduard",
                    sender_name="Eduard",
                    text="Can we increase CPA for Indonesia PWA traffic?",
                    timestamp=current - timedelta(hours=2, minutes=10),
                ),
                _msg(
                    platform=Platform.TELEGRAM,
                    chat_id=eduard_chat.external_id,
                    chat_name=eduard_chat.name,
                    external_id="tg-eduard-2",
                    sender_id="tg-user-eduard",
                    sender_name="Eduard",
                    text="We can provide more volume if CPA is approved.",
                    timestamp=current - timedelta(hours=1, minutes=55),
                ),
            ],
        ),
    ]


def conversations_for_platform(
    platform: Platform,
    now: datetime | None = None,
) -> list[MockConversation]:
    return [item for item in build_mock_conversations(now) if item.chat.platform == platform]


def senders_for_platform(platform: Platform, now: datetime | None = None) -> list[UnifiedSender]:
    seen: dict[str, UnifiedSender] = {}
    for conversation in conversations_for_platform(platform, now):
        for message in conversation.messages:
            if not message.sender_id or not message.sender_name:
                continue
            seen[message.sender_id] = UnifiedSender(
                platform=platform,
                external_id=message.sender_id,
                name=message.sender_name,
            )
    return list(seen.values())
