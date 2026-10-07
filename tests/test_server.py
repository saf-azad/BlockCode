from fastapi.testclient import TestClient

from blockcode.server import create_app


def test_health(tmp_path):
    client = TestClient(create_app(tmp_path))
    assert client.get("/api/health").json()["ok"] is True
