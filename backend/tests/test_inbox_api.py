from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import ConversationStatus
from app.models import AIAnalysis, Chat, Message
from app.services.inbox import list_chat_summaries


def test_get_chats_works(api_client: TestClient) -> None:
    seed = api_client.post("/dev/seed")
    assert seed.status_code == 200

    response = api_client.get("/chats")
    assert response.status_code == 200
    chats = response.json()
    assert len(chats) >= 3
    platforms = {item["platform"] for item in chats}
    assert {"typex", "slack", "telegram"} <= platforms
    assert "last_message_preview" in chats[0]
    timestamps = [item["last_message_at"] for item in chats if item["last_message_at"]]
    assert timestamps == sorted(timestamps, reverse=True)


def test_get_conversation_messages_works(api_client: TestClient) -> None:
    api_client.post("/dev/seed")
    chats = api_client.get("/chats").json()
    jackie = next(item for item in chats if item["name"] == "Jacqueline")

    response = api_client.get(f"/chats/{jackie['id']}/messages")
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) == 4
    texts = [item["text"] for item in messages]
    assert texts[0] == "Hi Igor"
    assert "What's the current welcome offer?" in texts


def test_patch_status_works(api_client: TestClient) -> None:
    api_client.post("/dev/seed")
    chats = api_client.get("/chats").json()
    chat_id = chats[0]["id"]

    response = api_client.patch(
        f"/chats/{chat_id}/status",
        json={"status": ConversationStatus.RESOLVED.value},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RESOLVED"

    refreshed = api_client.get(f"/chats/{chat_id}")
    assert refreshed.json()["status"] == "RESOLVED"


def test_dev_seed_twice_does_not_create_duplicates(
    api_client: TestClient,
    db_session: Session,
) -> None:
    first = api_client.post("/dev/seed")
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["chats_created"] >= 3
    assert first_payload["messages_created"] >= 8

    chat_count = db_session.scalar(select(func.count()).select_from(Chat))
    message_count = db_session.scalar(select(func.count()).select_from(Message))

    second = api_client.post("/dev/seed")
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["chats_created"] == 0
    assert second_payload["messages_created"] == 0
    assert second_payload["chats_existing"] == chat_count
    assert second_payload["messages_existing"] == message_count
    assert db_session.scalar(select(func.count()).select_from(Chat)) == chat_count
    assert db_session.scalar(select(func.count()).select_from(Message)) == message_count


def test_inbox_summaries_preview_count_and_sort(api_client: TestClient, db_session: Session) -> None:
    api_client.post("/dev/seed")
    summaries = list_chat_summaries(db_session)
    assert summaries[0].name == "Jacqueline"
    jackie = next(item for item in summaries if item.name == "Jacqueline")
    assert jackie.last_sender_name == "Jacqueline"
    assert jackie.last_message_preview is not None
    assert "Any promo for newly signed" in jackie.last_message_preview
    assert jackie.message_count == 4
    timestamps = [item.last_message_at for item in summaries if item.last_message_at]
    assert timestamps == sorted(timestamps, reverse=True)


def test_get_and_post_chat_analysis(api_client: TestClient) -> None:
    api_client.post("/dev/seed")
    chats = api_client.get("/chats").json()
    eduard = next(item for item in chats if "Eduard" in item["name"])

    missing = api_client.get(f"/chats/{eduard['id']}/analysis")
    assert missing.status_code == 404

    created = api_client.post(f"/chats/{eduard['id']}/analyze")
    assert created.status_code == 200
    payload = created.json()
    assert payload["priority"] == "high"
    assert payload["needs_igor"] is True

    fetched = api_client.get(f"/chats/{eduard['id']}/analysis")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == payload["id"]

    again = api_client.post(f"/chats/{eduard['id']}/analyze")
    assert again.json()["id"] == payload["id"]


def test_dev_analyze_all_is_idempotent(api_client: TestClient, db_session: Session) -> None:
    api_client.post("/dev/seed")
    first = api_client.post("/dev/analyze-all")
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["analyzed"] == 5
    assert first_payload["existing"] == 0
    assert first_payload["skipped"] == 0
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 5

    second = api_client.post("/dev/analyze-all")
    assert second.json()["analyzed"] == 0
    assert second.json()["existing"] == 5
    assert db_session.scalar(select(func.count()).select_from(AIAnalysis)) == 5


def test_chat_summary_includes_ai_priority(api_client: TestClient) -> None:
    api_client.post("/dev/seed")
    api_client.post("/dev/analyze-all")
    chats = api_client.get("/chats").json()
    eduard = next(item for item in chats if "Eduard" in item["name"])
    assert eduard["ai_priority"] == "high"
    assert eduard["ai_needs_igor"] is True
    jackie = next(item for item in chats if item["name"] == "Jacqueline")
    assert jackie["ai_priority"] == "normal"
    john = next(item for item in chats if item["name"] == "Affiliate John")
    assert john["ai_priority"] == "low"
    assert john["ai_needs_reply"] is False
