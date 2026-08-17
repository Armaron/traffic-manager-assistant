from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Traffic Manager Assistant"
    assert "version" in payload
    assert payload["typex_mode"] in {"mock", "real"}
    assert payload["ai_provider"]
