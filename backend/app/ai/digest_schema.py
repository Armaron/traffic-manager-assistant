DIGEST_SCHEMA_NAME = "traffic_cross_chat_work_review"
DIGEST_SCHEMA_VERSION = 2

DIGEST_SYSTEM_PROMPT = """You create a factual Russian WORK REVIEW of a traffic manager's period.

Igor is the operator. Use only the supplied JSON. Do not invent names, numbers, dates, approvals, deals, or missing context.
Preserve numbers, currencies and terms exactly: CPA, qCPA, CPC, CPM, FTD, qFTD, RevShare, Hybrid, GEO, PWA, MMP, APK, ROI, ROAS, KPI.
Do not translate those abbreviations.

This is a work review, not a one-line ops alert. Adapt length to activity:
- 1–3 chats: concise
- 10–20 active chats: a real review, roughly 800–2000 Russian words across all fields, without filler

Separate strictly:
- what actually happened
- what Igor wrote / sent (confirmed outgoing only)
- what the other side asked
- what was agreed (only if the source says so)
- waiting states
- required decisions
- AI assumptions (do not present assumptions as facts)

Never convert future intent into a completed action:
- "I will send" / "I'll send" → "Игорь сообщил, что отправит …" NOT "Игорь отправил …"
- "I'll check" / "I will check" → "Игорь сообщил, что уточнит / проверит." NOT "Игорь проверил."
- "We can discuss" → not an agreement
- "Can we do CPA $20?" → "Партнёр спросил о CPA $20." NEVER "Согласован CPA $20" or "нужно согласиться"

Direction rules:
- Only direction=outgoing is Igor's action or "С кем общался Игорь"
- direction=unknown must NEVER be described as Igor's message
- incoming-only chats do not belong in interactions / igor_actions

Do not treat stale analysis flags as truth. Prefer chronology and supplied messages.
Do not copy file/DOM UI garbage. If text is a file placeholder, say that a file/invoice was sent, using the filename if present. Do not invent file contents.

Commercial / high-stakes: summarize the REQUEST, not a DECISION.
Never recommend accepting CPA, raising budget, confirming payout, approving an affiliate, or changing a cap.

Needs-action items must be concrete: who/chat, what, why.
Forbidden empty actions: "продолжить коммуникацию", "контролировать переговоры", "мониторить ситуацию", "держать вопрос на контроле" unless you can name the person, the expected artefact, and why.

Do not repeat the same thought in four sections. No management clichés.

executive_summary_ru: 4–8 sentences covering volume, main workstreams, what Igor already did, what remains, and the main blocker if any.

main_events: 3–8 notable events, not only urgent (new lead, stats sent, report, blocker, commercial request, approval, closed deal if explicit).

igor_actions: only confirmed outgoing, skip ACK/ok/thanks. confidence=explicit when the outgoing text itself states the action; uncertain if inferred.

interactions: only chats with confirmed outgoing in the period. If outcome is unknown: "Диалог продолжается" or "Ждём ответ партнёра" — do not invent an outcome.

waiting_for_others: Igor already sent the latest meaningful message; describe whom we wait for and what, only from text.

completed_or_answered: distinguish "Игорь ответил; новых сообщений пока нет" from fully resolved. Do not say "вопрос закрыт" unless the source says so.

results_and_numbers: copy explicit figures exactly. Do not recalculate.

period_stats: copy the supplied review_stats numbers. Do not invent counters.

All user-facing strings are Russian. chat_id and message_id must be taken from supplied chats/messages only.
inside_period=false messages are CONTEXT only, not events of this period.

Output must match the JSON schema.
"""


def _ref(extra: dict | None = None) -> dict:
    props = {
        "chat_id": {"type": "integer"},
        "message_id": {"type": ["integer", "null"]},
        "source_message_ids": {"type": "array", "items": {"type": "integer"}},
        "title_ru": {"type": "string"},
        "summary_ru": {"type": "string"},
        "next_action_ru": {"type": "string"},
        "action_ru": {"type": "string"},
    }
    if extra:
        props.update(extra)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": list(props.keys()),
    }


def digest_result_json_schema() -> dict:
    action = _ref(
        {
            "person_or_chat_ru": {"type": "string"},
            "result_ru": {"type": "string"},
            "confidence": {"type": "string", "enum": ["explicit", "strong", "uncertain"]},
        }
    )
    interaction = _ref(
        {
            "person_or_chat_ru": {"type": "string"},
            "platform": {"type": "string"},
            "topic_ru": {"type": "string"},
            "what_happened_ru": {"type": "string"},
            "igor_last_action_ru": {"type": "string"},
            "current_state_ru": {"type": "string"},
        }
    )
    fact = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "chat_id": {"type": "integer"},
            "message_id": {"type": ["integer", "null"]},
            "source_message_ids": {"type": "array", "items": {"type": "integer"}},
            "fact_ru": {"type": "string"},
        },
        "required": ["chat_id", "message_id", "source_message_ids", "fact_ru"],
    }
    stats = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "active_chats": {"type": "integer"},
            "messages": {"type": "integer"},
            "igor_participated_chats": {"type": "integer"},
            "waiting_for_us": {"type": "integer"},
            "waiting_for_them": {"type": "integer"},
        },
        "required": [
            "active_chats",
            "messages",
            "igor_participated_chats",
            "waiting_for_us",
            "waiting_for_them",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title_ru": {"type": "string"},
            "executive_summary_ru": {"type": "string"},
            "period_stats": stats,
            "main_events": {"type": "array", "items": _ref()},
            "igor_actions": {"type": "array", "items": action},
            "interactions": {"type": "array", "items": interaction},
            "needs_action": {"type": "array", "items": _ref()},
            "waiting_for_others": {"type": "array", "items": _ref()},
            "completed_or_answered": {"type": "array", "items": _ref()},
            "results_and_numbers": {"type": "array", "items": fact},
            "blockers_and_risks": {"type": "array", "items": _ref()},
            "next_steps": {"type": "array", "items": _ref()},
        },
        "required": [
            "title_ru",
            "executive_summary_ru",
            "period_stats",
            "main_events",
            "igor_actions",
            "interactions",
            "needs_action",
            "waiting_for_others",
            "completed_or_answered",
            "results_and_numbers",
            "blockers_and_risks",
            "next_steps",
        ],
    }
