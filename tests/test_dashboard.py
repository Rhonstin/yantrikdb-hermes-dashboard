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


def test_memories_all_namespaces_sql_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "yantrikdb.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE memories (
                rid TEXT PRIMARY KEY, type TEXT, text TEXT, created_at REAL, updated_at REAL,
                importance REAL, half_life REAL, last_access REAL, access_count INTEGER,
                valence REAL, consolidated_into TEXT, consolidation_status TEXT,
                storage_tier TEXT, metadata TEXT, namespace TEXT, certainty REAL,
                domain TEXT, source TEXT, emotional_state TEXT, session_id TEXT,
                due_at REAL, temporal_kind TEXT, tombstone_reason TEXT,
                embedding_model TEXT, embedding BLOB
            )
        """)
        rows = [
            ("r1", "semantic", "alpha", 2, 2, .8, None, 2, 0, None, None, "active", None, "{}", "ns:a", .8, "general", "user", None, None, None, None, None, None, None),
            ("r2", "semantic", "beta", 1, 1, .5, None, 1, 0, None, None, "active", None, "{}", "ns:b", .5, "general", "user", None, None, None, None, None, None, None),
        ]
        conn.executemany("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)

    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    result = dashboard.memories(namespace="__all__", status="active", limit=10, offset=0)
    assert result["total"] == 2
    assert {item["namespace"] for item in result["items"]} == {"ns:a", "ns:b"}


def test_constellation_all_namespaces_builds_scope_hubs(tmp_path, monkeypatch):
    db_path = tmp_path / "yantrikdb.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE memories (
                rid TEXT PRIMARY KEY, text TEXT, domain TEXT, source TEXT, type TEXT,
                importance REAL, created_at REAL, updated_at REAL, access_count INTEGER,
                consolidation_status TEXT, namespace TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("rid-alpha-0001", "Alpha project uses YantrikDB visualiser", "work", "user", "semantic", .9, 3, 3, 0, "active", "ns:a"),
                ("rid-beta-0002", "Beta household memory graph", "home", "assistant", "semantic", .8, 2, 2, 0, "active", "ns:b"),
            ],
        )

    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    result = dashboard.constellation(namespace="__all__", limit=40)
    labels = {node["label"] for node in result["nodes"]}
    categories = {node["category"] for node in result["nodes"]}
    assert result["all_namespaces"] is True
    assert "a" in labels
    assert "b" in labels
    assert categories >= {"a", "b"}
    assert any(edge["kind"] == "scope" for edge in result["edges"])
    assert {cluster["label"] for cluster in result["clusters"]} >= {"a", "b"}


def test_constellation_all_namespaces_does_not_merge_same_label_across_scopes(tmp_path, monkeypatch):
    db_path = tmp_path / "yantrikdb.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE memories (
                rid TEXT PRIMARY KEY, text TEXT, domain TEXT, source TEXT, type TEXT,
                importance REAL, created_at REAL, updated_at REAL, access_count INTEGER,
                consolidation_status TEXT, namespace TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                ("rid-alpha-0001", "Shared Topic appears here", "shared", "user", "semantic", .9, 3, 3, 0, "active", "ns:a"),
                ("rid-beta-0002", "Shared Topic appears there", "shared", "user", "semantic", .8, 2, 2, 0, "active", "ns:b"),
            ],
        )

    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    result = dashboard.constellation(namespace="__all__", limit=80)
    shared_nodes = [node for node in result["nodes"] if node["label"] == "shared"]
    assert len(shared_nodes) == 2
    assert {node["namespace"] for node in shared_nodes} == {"ns:a", "ns:b"}


def test_constellation_all_namespaces_balances_scope_sampling(tmp_path, monkeypatch):
    db_path = tmp_path / "yantrikdb.db"
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE memories (
                rid TEXT PRIMARY KEY, text TEXT, domain TEXT, source TEXT, type TEXT,
                importance REAL, created_at REAL, updated_at REAL, access_count INTEGER,
                consolidation_status TEXT, namespace TEXT
            )
        """)
        rows = []
        for i in range(70):
            rows.append((f"big-{i:03d}", f"Big namespace memory {i}", "shared", "user", "semantic", 1.0, 1000 - i, 1000 - i, 0, "active", "ns:big"))
        for i in range(5):
            rows.append((f"small-{i:03d}", f"Small namespace memory {i}", "shared", "user", "semantic", .2, 10 - i, 10 - i, 0, "active", "ns:small"))
        conn.executemany("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)

    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    result = dashboard.constellation(namespace="__all__", limit=40)
    namespaces = {node["namespace"] for node in result["nodes"] if node.get("namespace")}
    assert {"ns:big", "ns:small"} <= namespaces
    assert any(edge.get("item", {}).get("namespace") == "ns:small" for edge in result["edges"])


def test_index_has_memory_namespace_filter_and_maintenance_label():
    html = (Path(dashboard.STATIC_DIR) / "index.html").read_text()
    assert "memoryNamespaceFilter" in html
    assert "Maintenance" in html
    assert "think()</button>" not in html
