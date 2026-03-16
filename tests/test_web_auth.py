import base64
import pytest
from fastapi.testclient import TestClient
from src.config import Settings
from src.dashboard.web import create_app


@pytest.fixture
def app_with_auth(tmp_path):
    settings = Settings(DASHBOARD_PASSWORD="secret123", DB_PATH=str(tmp_path / "test.db"))
    app = create_app(settings=settings)
    return app


@pytest.fixture
def app_no_auth(tmp_path):
    settings = Settings(DASHBOARD_PASSWORD="", DB_PATH=str(tmp_path / "test.db"))
    app = create_app(settings=settings)
    return app


def test_auth_required_blocks_unauthenticated(app_with_auth):
    client = TestClient(app_with_auth)
    resp = client.get("/")
    assert resp.status_code == 401


def test_auth_required_allows_correct_password(app_with_auth):
    client = TestClient(app_with_auth)
    creds = base64.b64encode(b"admin:secret123").decode()
    resp = client.get("/", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 200


def test_auth_required_rejects_wrong_password(app_with_auth):
    client = TestClient(app_with_auth)
    creds = base64.b64encode(b"admin:wrong").decode()
    resp = client.get("/", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 401


def test_no_auth_when_password_empty(app_no_auth):
    client = TestClient(app_no_auth)
    resp = client.get("/")
    assert resp.status_code == 200
