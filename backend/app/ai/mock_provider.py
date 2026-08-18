from app.enums import AnalysisCategory, Priority
from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult, ImportantEntities
from app.ai.provider import AIProvider


def _result(**kwargs: object) -> AIAnalysisResult:
    return AIAnalysisResult.model_validate(kwargs)


_FIXTURES: list[tuple[str, AIAnalysisResult]] = [
    (
        "welcome offer",
        _result(
            summary="Партнёр спрашивает актуальное приветственное предложение.",
            request="Получить условия welcome offer.",
            category=AnalysisCategory.AFFILIATE,
            priority=Priority.NORMAL,
            needs_reply=True,
            needs_igor=False,
            reason="На вопрос можно ответить, если актуальные условия есть во внутренней базе.",
            draft_reply="Hi Jacqueline, sure. I'll share the current welcome offer with you.",
            important_entities=ImportantEntities(),
        ),
    ),
    (
        "promo for newly signed",
        _result(
            summary="Партнёр спрашивает промо для новых аффилиатов.",
            request="Получить текущее promo для newly signed affiliates.",
            category=AnalysisCategory.PROMO,
            priority=Priority.NORMAL,
            needs_reply=True,
            needs_igor=False,
            reason="Это коммерческий вопрос по офферу, на него можно ответить после проверки актуальных условий.",
            draft_reply="Hi Jacqueline, I'll confirm the current promo for newly signed affiliates and send it over.",
            important_entities=ImportantEntities(),
        ),
    ),
    (
        "increase cpa",
        _result(
            summary="Партнёр хочет изменить CPA для Indonesia PWA.",
            request="Получить approval на увеличение CPA.",
            category=AnalysisCategory.AD_NETWORK,
            priority=Priority.HIGH,
            needs_reply=True,
            needs_igor=True,
            reason="Запрос касается изменения коммерческих условий и требует внутреннего решения.",
            draft_reply="Hi Eduard, thanks. Let me confirm the CPA internally and I'll get back to you.",
            important_entities=ImportantEntities(
                geo=["Indonesia"],
                traffic_source=["PWA"],
                payment_model=["CPA"],
            ),
        ),
    ),
    (
        "more volume if cpa",
        _result(
            summary="Партнёр готов увеличить объём, если CPA будет согласован.",
            request="Подтверждение CPA для дополнительного объёма Indonesia PWA.",
            category=AnalysisCategory.AD_NETWORK,
            priority=Priority.HIGH,
            needs_reply=True,
            needs_igor=True,
            reason="Коммерческие условия и объём трафика требуют внутреннего approval.",
            draft_reply="Hi Eduard, thanks. Let me confirm the CPA internally and I'll get back to you.",
            important_entities=ImportantEntities(
                geo=["Indonesia"],
                traffic_source=["PWA"],
                payment_model=["CPA"],
            ),
        ),
    ),
    (
        "started traffic",
        _result(
            summary="Партнёр сообщил, что запуск трафика состоялся.",
            request="Информационное сообщение.",
            category=AnalysisCategory.AFFILIATE,
            priority=Priority.LOW,
            needs_reply=False,
            needs_igor=False,
            reason="Это статусный апдейт, срочный ответ не требуется.",
            draft_reply=None,
            important_entities=ImportantEntities(),
        ),
    ),
    (
        "stats tomorrow",
        _result(
            summary="Партнёр обещает прислать первую статистику завтра.",
            request="Информационное сообщение.",
            category=AnalysisCategory.REPORT,
            priority=Priority.LOW,
            needs_reply=False,
            needs_igor=False,
            reason="Ждём статистику, сейчас отвечать не обязательно.",
            draft_reply=None,
            important_entities=ImportantEntities(),
        ),
    ),
    (
        "affiliates proposed for launch",
        _result(
            summary="Коллега просит список аффилиатов для запуска.",
            request="Прислать список предложенных affiliates.",
            category=AnalysisCategory.INTERNAL,
            priority=Priority.HIGH,
            needs_reply=True,
            needs_igor=False,
            reason="Внутренний рабочий запрос, нужен ответ со списком.",
            draft_reply="I'll send the affiliate list today.",
            important_entities=ImportantEntities(),
        ),
    ),
    (
        "no action needed",
        _result(
            summary="Информационное сообщение: по Indonesia PWA действий не требуется.",
            request="FYI, без запроса.",
            category=AnalysisCategory.INTERNAL,
            priority=Priority.LOW,
            needs_reply=False,
            needs_igor=False,
            reason="Это FYI, ответ не нужен.",
            draft_reply=None,
            important_entities=ImportantEntities(geo=["Indonesia"], traffic_source=["PWA"]),
        ),
    ),
]


class MockAIProvider(AIProvider):
    """Deterministic local analysis. Does not call any network API."""

    name = "mock"
    model = "mock-v1"
    resolved_model = "mock-v1"

    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        text = context.current_message.text.lower()
        for needle, result in _FIXTURES:
            if needle in text:
                return _explained(result, context)
        sender = context.current_message.sender_name or "there"
        return _explained(
            AIAnalysisResult(
                summary="Короткое рабочее сообщение, требующее обычного ответа.",
                request="Уточнить детали и ответить отправителю.",
                category=AnalysisCategory.OTHER,
                priority=Priority.NORMAL,
                needs_reply=True,
                needs_igor=False,
                reason="Для этого сообщения нет отдельного mock-сценария, нужен обычный follow-up.",
                draft_reply=f"Hi {sender}, thanks. I'll check and get back to you.",
                important_entities=ImportantEntities(),
            ),
            context,
        )


_TERM_GLOSSARY: tuple[tuple[str, str], ...] = (
    ("cpa", "CPA — оплата за одного привлечённого игрока, выполнившего условие оффера."),
    ("ftd", "FTD — первый депозит нового игрока."),
    ("revshare", "RevShare — доля от дохода казино вместо фиксированной выплаты."),
    ("cpc", "CPC — оплата за один клик по рекламе."),
    ("pwa", "PWA — веб-приложение, которое ставится на телефон как обычное приложение."),
    ("geo", "GEO — страна или регион, из которого идёт трафик."),
    ("cap", "cap — предел по количеству игроков или расходу за период."),
    ("budget", "budget — бюджет, который партнёр готов открутить."),
    ("creative", "creative — рекламный материал: баннер, видео или текст объявления."),
    ("landing", "landing page — страница, куда попадает пользователь после клика."),
    ("welcome offer", "welcome offer — приветственный бонус для новых игроков."),
)


def _explained(result: AIAnalysisResult, context: AIAnalysisContext) -> AIAnalysisResult:
    """Fixtures hold short fields; the panel needs a Russian walkthrough and a next step."""
    if result.conversation_explanation_ru and result.next_action_ru:
        return result
    return result.model_copy(
        update={
            "conversation_explanation_ru": result.conversation_explanation_ru
            or _mock_explanation(result, context),
            "next_action_ru": result.next_action_ru or _mock_next_action(result, context),
        }
    )


def _mock_explanation(result: AIAnalysisResult, context: AIAnalysisContext) -> str:
    sender = context.current_message.sender_name or "собеседник"
    parts = [
        f"Переписка в чате «{context.chat.name}». {result.summary}",
        f"Что хочет {sender}: {result.request}",
    ]
    if context.already_answered:
        parts.append(
            "После этого сообщения наша сторона уже отправила ответ, поэтому отвечать заново не нужно."
        )
    elif result.needs_reply:
        parts.append("Ответа с нашей стороны пока нет, поэтому вопрос остаётся открытым.")
    else:
        parts.append("Ответ по смыслу не требуется: сообщение не содержит вопроса или просьбы.")
    parts.append(result.reason)
    if result.needs_igor:
        parts.append(
            "Коммерческие условия здесь решает Игорь, поэтому вопрос нужно передать ему, "
            "а не подтверждать самостоятельно."
        )
    parts.extend(_glossary(f"{context.current_message.text} {result.summary} {result.request}"))
    return " ".join(part.strip() for part in parts if part.strip())


def _mock_next_action(result: AIAnalysisResult, context: AIAnalysisContext) -> str:
    if context.already_answered:
        return "Ничего делать не нужно — ответ уже отправлен."
    if result.needs_igor:
        return "Передать вопрос Игорю и дождаться его решения."
    if result.needs_reply:
        sender = context.current_message.sender_name or "собеседнику"
        return f"Ответить {sender} по сути вопроса."
    return "Ответ не нужен, держать переписку на контроле."


def _glossary(text: str) -> list[str]:
    lowered = text.lower()
    return [explanation for needle, explanation in _TERM_GLOSSARY if needle in lowered]
