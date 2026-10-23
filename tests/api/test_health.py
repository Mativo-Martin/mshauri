from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app


def test_health_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_reports_version() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(app_version="abc123")
    resp = TestClient(app).get("/health")
    assert resp.json() == {"status": "ok", "version": "abc123"}
