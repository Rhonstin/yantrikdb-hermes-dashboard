from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as dashboard


def test_index_serves_static_html():
    client = TestClient(dashboard.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "YantrikDB Dashboard" in response.text
    assert "brandHome" in response.text


def test_admin_requires_admin_mode_when_disabled(monkeypatch):
    monkeypatch.setattr(dashboard, "ADMIN_MODE_ENV", False)
    monkeypatch.setattr(dashboard, "load_dashboard_settings", lambda: {})
    with pytest.raises(dashboard.HTTPException) as exc:
        dashboard.require_admin(None)
    assert exc.value.status_code == 403
    assert "Admin mode is disabled" in exc.value.detail


def test_admin_accepts_env_admin_mode(monkeypatch):
    monkeypatch.setattr(dashboard, "ADMIN_MODE_ENV", True)
    dashboard.require_admin(None)


def test_admin_accepts_stored_admin_mode(monkeypatch):
    monkeypatch.setattr(dashboard, "ADMIN_MODE_ENV", False)
    monkeypatch.setattr(dashboard, "load_dashboard_settings", lambda: {"admin_mode": True})
    dashboard.require_admin(None)


def test_infer_embedding_dim_from_sqlite_blob(tmp_path, monkeypatch):
    db_path = tmp_path / "yantrikdb.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (embedding BLOB)")
        conn.execute("INSERT INTO memories VALUES (?)", (b"0" * (512 * 4),))

    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.delenv("YANTRIKDB_EMBEDDING_DIM", raising=False)
    assert dashboard.infer_embedding_dim() == 512


def test_static_assets_exist():
    assert (Path(dashboard.STATIC_DIR) / "index.html").exists()
    assert (Path(dashboard.STATIC_DIR) / "app.js").exists()
    assert (Path(dashboard.STATIC_DIR) / "styles.css").exists()
    assert (Path(dashboard.STATIC_DIR) / "assets" / "favicon.svg").exists()


def test_three_visualiser_css_has_bounded_viewport():
    css = (Path(dashboard.STATIC_DIR) / "styles.css").read_text()
    assert ".three-viewport" in css
    assert "height:650px" in css
    assert "min-height:650px" in css
    assert ".three-viewport canvas" in css
    assert "position:absolute" in css
    assert "height:100%" in css


def test_password_gate_login_and_cookie_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(dashboard, "ADMIN_MODE_ENV", False)
    client = TestClient(dashboard.app)

    response = client.post("/api/settings", json={"admin_mode": False, "new_password": "old-pass"})
    assert response.status_code == 200
    assert "yantrikdb_dashboard_session" in response.headers.get("set-cookie", "")
    assert client.get("/api/health").status_code == 401

    assert client.post("/api/auth/login", json={"password": "old-pass"}).status_code == 200
    assert client.get("/api/settings").status_code == 200

    response = client.post("/api/settings", json={"admin_mode": False, "new_password": "new-pass"})
    assert response.status_code == 200
    assert client.get("/api/settings").status_code == 401
    assert client.post("/api/auth/login", json={"password": "old-pass"}).status_code == 403
    assert client.post("/api/auth/login", json={"password": "new-pass"}).status_code == 200


def test_disabling_password_clears_cookie_and_opens_api(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    client = TestClient(dashboard.app)
    assert client.post("/api/settings", json={"admin_mode": False, "new_password": "pass"}).status_code == 200
    assert client.post("/api/auth/login", json={"password": "pass"}).status_code == 200
    response = client.post("/api/settings", json={"admin_mode": False, "disable_password": True})
    assert response.status_code == 200
    assert "yantrikdb_dashboard_session" in response.headers.get("set-cookie", "")
    assert client.get("/api/settings").status_code == 200
