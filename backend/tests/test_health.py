from fastapi.testclient import TestClient


def test_health_reports_db_ok(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok"}
