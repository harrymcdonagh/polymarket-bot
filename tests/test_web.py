import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture
def client(tmp_path):
    with patch("src.dashboard.service.Pipeline") as MockPipeline:
        MockPipeline.return_value = MagicMock()
        from src.dashboard.web import create_app
        app = create_app(db_path=str(tmp_path / "test.db"))
        from fastapi.testclient import TestClient
        yield TestClient(app)


def test_get_stats(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_trades" in data
    assert "win_rate" in data


def test_get_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "loop_active" in data
    assert "cycle_count" in data
    assert "last_error" in data


def test_get_trades(client):
    resp = client.get("/api/trades")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_logs(client):
    resp = client.get("/api/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_pnl_history(client):
    resp = client.get("/api/pnl-history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_markets(client):
    resp = client.get("/api/markets")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_get_lessons(client):
    resp = client.get("/api/lessons")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_post_scan(client):
    resp = client.post("/api/scan", json={"dry_run": True})
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_post_retrain(client):
    resp = client.post("/api/retrain")
    assert resp.status_code == 202
    assert resp.json()["status"] == "started"


def test_post_loop(client):
    resp = client.post("/api/loop", json={"interval": 300})
    assert resp.status_code == 200
    assert "loop" in resp.json()


def test_post_settings_invalid_key(client):
    resp = client.post("/api/settings", json={"key": "ANTHROPIC_API_KEY", "value": "hacked"})
    assert resp.status_code == 400


def test_post_settings_valid(client):
    resp = client.post("/api/settings", json={"key": "BANKROLL", "value": 2000})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
