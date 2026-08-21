import re

from app.enums import AnalysisCategory, Priority
from app.schemas.analysis import AIAnalysisContext, AIAnalysisResult, ImportantEntities
from app.schemas.digest import (
    DigestAIAction,
    DigestAIEntry,
    DigestAIFact,
    DigestAIInteraction,
    DigestAIOutput,
    DigestAIPeriodStats,
    DigestQAModelOutput,
)
from app.ai.provider import AIProvider
from app.services.digest_context import (
    describe_outgoing_action,
    incoming_is_unapproved_request,
    is_ack,
    normalize_digest_text,
)


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

    def __init__(self) -> None:
        self.digest_calls = 0
        self.qa_calls = 0
        self.analyze_calls = 0

    async def analyze_message(self, context: AIAnalysisContext) -> AIAnalysisResult:
        self.analyze_calls += 1
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

    async def summarize_digest(self, payload: dict) -> DigestAIOutput:
        self.digest_calls += 1
        chats = [chat for chat in (payload.get("chats") or []) if isinstance(chat, dict)]
        stats = payload.get("review_stats") if isinstance(payload.get("review_stats"), dict) else {}
        counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
        active = int(stats.get("active_chats") or counts.get("active_chats") or 0)
        messages_n = int(stats.get("messages") or counts.get("messages") or 0)
        igor_n = int(stats.get("igor_participated_chats") or counts.get("igor_participated") or 0)
        wait_us = int(stats.get("waiting_for_us") or counts.get("needs_reply") or 0)
        wait_them = int(stats.get("waiting_for_them") or counts.get("waiting") or 0)

        interactions: list[DigestAIInteraction] = []
        actions: list[DigestAIAction] = []
        needs: list[DigestAIEntry] = []
        waiting: list[DigestAIEntry] = []
        completed: list[DigestAIEntry] = []
        events: list[DigestAIEntry] = []
        numbers: list[DigestAIFact] = []
        blockers: list[DigestAIEntry] = []
        next_steps: list[DigestAIEntry] = []

        for chat in chats:
            chat_id = int(chat.get("chat_id") or 0)
            name = str(chat.get("chat_name") or "Чат")
            platform = str(chat.get("platform") or "")
            msgs = [m for m in (chat.get("messages") or []) if isinstance(m, dict)]
            in_period = [m for m in msgs if m.get("inside_period") is not False]
            outgoing = [
                m
                for m in in_period
                if m.get("direction") == "outgoing" and not m.get("low_information")
            ]
            incoming = [m for m in in_period if m.get("direction") == "incoming"]
            unknown = [m for m in in_period if m.get("direction") == "unknown"]
            last_out = outgoing[-1] if outgoing else None
            last_in = incoming[-1] if incoming else None
            target = chat.get("target_message_id") or (last_in or last_out or {}).get("id")
            source_ids = [int(m["id"]) for m in in_period if isinstance(m.get("id"), int)]

            for msg in outgoing:
                text = str(msg.get("text") or "")
                if is_ack(text):
                    continue
                action_ru, confidence = describe_outgoing_action(text)
                actions.append(
                    DigestAIAction(
                        chat_id=chat_id,
                        message_id=msg.get("id"),
                        source_message_ids=[int(msg["id"])] if isinstance(msg.get("id"), int) else [],
                        person_or_chat_ru=name,
                        action_ru=action_ru,
                        result_ru="",
                        confidence=confidence,  # type: ignore[arg-type]
                        title_ru=name,
                        summary_ru=action_ru,
                    )
                )

            if outgoing:
                last_text = str((last_out or {}).get("text") or "")
                igor_last, _ = describe_outgoing_action(last_text) if last_text else ("", "uncertain")
                if chat.get("waiting") or (last_out and (not last_in or _later(last_out, last_in))):
                    state = "Ждём ответ партнёра"
                elif chat.get("needs_reply"):
                    state = "Нужен ответ с нашей стороны"
                else:
                    state = "Диалог продолжается"
                topic = _topic(chat, incoming, outgoing)
                happened = _what_happened(name, incoming, outgoing)
                interactions.append(
                    DigestAIInteraction(
                        chat_id=chat_id,
                        message_id=target,
                        source_message_ids=source_ids[:8],
                        person_or_chat_ru=name,
                        platform=platform,
                        topic_ru=topic,
                        what_happened_ru=happened,
                        igor_last_action_ru=igor_last,
                        current_state_ru=state,
                        next_action_ru=_next_action(chat, name),
                        title_ru=name,
                        summary_ru=happened,
                    )
                )

            if chat.get("needs_reply") or chat.get("needs_igor") or chat.get("urgent"):
                reason = _next_action(chat, name)
                needs.append(
                    DigestAIEntry(
                        chat_id=chat_id,
                        message_id=target,
                        source_message_ids=source_ids[:4],
                        title_ru=name,
                        summary_ru=reason,
                        next_action_ru=reason,
                        action_ru=reason,
                    )
                )
                next_steps.append(needs[-1])
            if chat.get("waiting") and outgoing:
                waiting.append(
                    DigestAIEntry(
                        chat_id=chat_id,
                        message_id=target,
                        source_message_ids=source_ids[:4],
                        title_ru=name,
                        summary_ru=f"Ждём ответ {name}.",
                        next_action_ru=f"Проверить, ответил ли {name}.",
                        action_ru=f"Проверить, ответил ли {name}.",
                    )
                )
            if chat.get("already_answered") or chat.get("resolved"):
                completed.append(
                    DigestAIEntry(
                        chat_id=chat_id,
                        message_id=target,
                        source_message_ids=source_ids[:4],
                        title_ru=name,
                        summary_ru="Игорь ответил; новых сообщений пока нет."
                        if chat.get("already_answered")
                        else "Чат отмечен как закрытый.",
                    )
                )

            for msg in incoming + outgoing:
                text = str(msg.get("text") or "")
                if incoming_is_unapproved_request(text):
                    events.append(
                        DigestAIEntry(
                            chat_id=chat_id,
                            message_id=msg.get("id"),
                            source_message_ids=[int(msg["id"])] if isinstance(msg.get("id"), int) else [],
                            title_ru=name,
                            summary_ru=f"{name} спросил о коммерческих условиях. Это запрос, не договорённость.",
                        )
                    )
                    if chat.get("high_stakes") or chat.get("needs_igor"):
                        blockers.append(
                            DigestAIEntry(
                                chat_id=chat_id,
                                message_id=msg.get("id"),
                                title_ru=name,
                                summary_ru=f"Партнёр запросил условия; требуется решение Игоря. Не подтверждать самостоятельно.",
                            )
                        )
                for fact in _extract_numbers(text):
                    numbers.append(
                        DigestAIFact(
                            chat_id=chat_id,
                            message_id=msg.get("id"),
                            source_message_ids=[int(msg["id"])] if isinstance(msg.get("id"), int) else [],
                            fact_ru=fact,
                        )
                    )
                normalized = normalize_digest_text(text)
                if normalized.startswith("[File]"):
                    events.append(
                        DigestAIEntry(
                            chat_id=chat_id,
                            message_id=msg.get("id"),
                            title_ru=name,
                            summary_ru=f"{name}: {normalized}.",
                        )
                    )

            if unknown:
                # Explicitly unused as Igor actions; keep a note only if no outgoing.
                pass

            if last_out or last_in or chat.get("urgent") or chat.get("needs_igor"):
                events.append(
                    DigestAIEntry(
                        chat_id=chat_id,
                        message_id=target,
                        source_message_ids=source_ids[:4],
                        title_ru=name,
                        summary_ru=_what_happened(name, incoming, outgoing) or str(chat.get("snippet") or ""),
                    )
                )

        events = _dedupe_entries(events)[:8]
        actions = actions[:12]
        unique_numbers = []
        seen_facts: set[str] = set()
        for item in numbers:
            if item.fact_ru in seen_facts:
                continue
            seen_facts.add(item.fact_ru)
            unique_numbers.append(item)

        summary = (
            f"За период {active} активных чатов и {messages_n} сообщений. "
            f"Игорь участвовал в {igor_n} переписках и ответил там, где есть исходящие. "
            f"Сейчас ждут нашего ответа {wait_us} чатов, ждут другую сторону {wait_them}. "
            f"Разбор построен только по переданным сообщениям: обещания не считаются выполненными действиями, "
            f"а коммерческие запросы не считаются договорённостями. "
            f"Главное — закрыть конкретные хвосты по чатам, где ещё нет ответа или нужно решение Игоря."
        )
        return DigestAIOutput(
            title_ru="Рабочее ревью периода",
            executive_summary_ru=summary,
            period_stats=DigestAIPeriodStats(
                active_chats=active,
                messages=messages_n,
                igor_participated_chats=igor_n,
                waiting_for_us=wait_us,
                waiting_for_them=wait_them,
            ),
            main_events=events,
            igor_actions=actions,
            interactions=interactions,
            needs_action=needs[:10],
            waiting_for_others=waiting[:10],
            completed_or_answered=completed[:10],
            results_and_numbers=unique_numbers[:12],
            blockers_and_risks=_dedupe_entries(blockers)[:8],
            next_steps=next_steps[:10] or waiting[:5],
        )

    async def answer_digest_qa(self, payload: dict) -> DigestQAModelOutput:
        self.qa_calls += 1
        question = str(payload.get("question") or "")
        sources = [item for item in (payload.get("sources") or []) if isinstance(item, dict)]
        in_period = [item for item in sources if item.get("inside_period") is not False]
        q = question.lower().replace("ё", "е")
        refs: list[str] = []
        lines: list[str] = []
        uncertainty = None

        def add(item: dict, text: str) -> None:
            alias = str(item.get("alias") or "")
            if alias and alias not in refs:
                refs.append(alias)
            lines.append(text)

        if not in_period:
            return DigestQAModelOutput(
                answer_ru="В выбранном периоде я не нашёл подтверждения этого.",
                source_refs=[],
                uncertainty_ru="В выбранном периоде недостаточно данных.",
                suggested_questions_ru=[],
            )

        if any(needle in q for needle in ("сделал игорь", "что сделал", "что игорь", "с кем общал")):
            for item in in_period:
                if item.get("direction") != "outgoing" or item.get("low_information"):
                    continue
                action, _ = describe_outgoing_action(str(item.get("text") or ""))
                add(item, f"{item.get('chat_name')}: {action}")
            if not lines:
                uncertainty = "В выбранном периоде нет подтверждённых исходящих действий Игоря."
        elif any(needle in q for needle in ("кому ответить", "надо ответить", "нужно ответить")):
            seen: set[str] = set()
            for item in in_period:
                if not item.get("needs_reply") or item.get("direction") == "outgoing":
                    continue
                name = str(item.get("chat_name") or "")
                if name in seen:
                    continue
                seen.add(name)
                add(item, f"{name} — ещё нет ответа на входящее.")
            if not lines:
                uncertainty = "В выбранном периоде нет чатов, которые явно ждут ответа."
        elif "cpa" in q or "цифр" in q:
            for item in in_period:
                text = str(item.get("text") or "")
                if "cpa" not in text.lower() and not incoming_is_unapproved_request(text) and "$" not in text:
                    continue
                if incoming_is_unapproved_request(text) or "?" in text:
                    add(
                        item,
                        f"{item.get('chat_name')}: партнёр спросил «{text}». В переписках нет подтверждения, что это согласовано.",
                    )
                else:
                    add(item, f"{item.get('chat_name')}: {text}")
        else:
            q_tokens = [token for token in q.split() if len(token) >= 4]
            hits: list[dict] = []
            for item in in_period:
                text = str(item.get("text") or "").lower()
                name = str(item.get("chat_name") or "").lower()
                if q_tokens and any(token in text or token in name for token in q_tokens):
                    hits.append(item)
            if not hits:
                return DigestQAModelOutput(
                    answer_ru="В выбранном периоде я не нашёл подтверждения этого.",
                    source_refs=[],
                    uncertainty_ru="В выбранном периоде недостаточно данных.",
                    suggested_questions_ru=[],
                )
            for item in hits:
                text = str(item.get("text") or "")
                if item.get("direction") == "unknown":
                    add(item, f"{item.get('chat_name')}: {text} (направление неизвестно, это не действие Игоря).")
                else:
                    add(item, f"{item.get('chat_name')}: {text}")

        if not lines:
            return DigestQAModelOutput(
                answer_ru="В выбранном периоде я не нашёл подтверждения этого.",
                source_refs=[],
                uncertainty_ru=uncertainty or "В выбранном периоде недостаточно данных.",
                suggested_questions_ru=[],
            )
        answer = " ".join(lines)
        if "ответить на cpa" in q or "что ответить" in q:
            answer += " Требуется решение Игоря; модель не одобряет коммерческие условия."
        return DigestQAModelOutput(
            answer_ru=answer,
            source_refs=refs,
            uncertainty_ru=uncertainty,
            suggested_questions_ru=[],
        )


def _later(left: dict, right: dict) -> bool:
    return str(left.get("timestamp") or "") >= str(right.get("timestamp") or "")


def _topic(chat: dict, incoming: list[dict], outgoing: list[dict]) -> str:
    blob = " ".join(str(m.get("text") or "") for m in incoming + outgoing)
    for needle, label in (
        ("invoice", "Invoice"),
        ("cpa", "CPA"),
        ("stats", "Статистика"),
        ("report", "Отчёт"),
        ("landing", "Landing"),
    ):
        if needle in blob.lower():
            return label
    return str(chat.get("chat_name") or "Рабочая переписка")


def _what_happened(name: str, incoming: list[dict], outgoing: list[dict]) -> str:
    parts = []
    if incoming:
        text = str(incoming[-1].get("text") or "")
        if incoming_is_unapproved_request(text):
            parts.append(f"{name} задал вопрос по условиям, это запрос, не соглашение.")
        else:
            parts.append(f"{name} написал: {_clip(text)}")
    if outgoing:
        action, _ = describe_outgoing_action(str(outgoing[-1].get("text") or ""))
        parts.append(action)
    return " ".join(parts)


def _next_action(chat: dict, name: str) -> str:
    if chat.get("needs_igor") or chat.get("high_stakes"):
        return f"Уточнить у Игоря допустимые условия перед ответом {name}."
    if chat.get("needs_reply"):
        return f"Ответить {name} по открытому вопросу."
    if chat.get("waiting"):
        return f"Проверить, ответил ли {name} на исходящее сообщение."
    return f"Проверить переписку с {name}."


def _extract_numbers(text: str) -> list[str]:
    found = []
    for match in re.finditer(
        r"(?i)(\d[\d\s,]*(?:\.\d+)?\s*(?:affiliate candidates approached|active negotiations|deal closed|FTD|qFTD|CPA)|CPA\s*\$?\s*[\d.]+|\$\s*[\d.]+|\d{1,3}(?:,\d{3})+\s*FTD)",
        text,
    ):
        found.append(match.group(0).strip())
    for match in re.finditer(r"\b(\d+)\s+affiliate candidates approached\b", text, re.I):
        found.append(match.group(0))
    for match in re.finditer(r"\b(\d+)\s+active negotiations\b", text, re.I):
        found.append(match.group(0))
    for match in re.finditer(r"\b(\d+)\s+(?:deal closed|closed)\b", text, re.I):
        found.append(match.group(0))
    return found


def _clip(text: str) -> str:
    value = " ".join(text.split())
    return value if len(value) <= 160 else value[:159] + "…"


def _dedupe_entries(items: list[DigestAIEntry]) -> list[DigestAIEntry]:
    seen: set[tuple[int, str]] = set()
    result: list[DigestAIEntry] = []
    for item in items:
        key = (item.chat_id, item.summary_ru)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


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
