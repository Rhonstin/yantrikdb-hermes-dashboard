from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

import app as dashboard


def test_index_serves_static_html():
    client = TestClient(dashboard.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "YantrikDB for Hermes" in response.text
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


def test_settings_exposes_and_updates_yantrikdb_runtime_config(tmp_path, monkeypatch):
    settings_path = tmp_path / "settings.json"
    config_path = tmp_path / "yantrikdb.json"
    config_path.write_text(json.dumps({
        "mode": "embedded",
        "namespace": "hermes",
        "top_k": "10",
        "owner_scoping": True,
        "include_base_namespace_recall": True,
        "include_legacy_actor_namespace_recall": True,
        "identity_map_path": str(tmp_path / "identity-map.json"),
    }))
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", config_path)
    monkeypatch.setattr(dashboard, "ADMIN_MODE_ENV", False)
    client = TestClient(dashboard.app)

    response = client.get("/api/settings")
    assert response.status_code == 200
    ycfg = response.json()["yantrikdb"]
    assert ycfg["owner_scoping"] is True
    assert ycfg["default_namespace"] == "hermes:hermes:default"

    response = client.post("/api/settings", json={
        "admin_mode": True,
        "owner_scoping": False,
        "include_base_namespace_recall": False,
        "include_legacy_actor_namespace_recall": True,
        "top_k": 7,
    })
    assert response.status_code == 200
    saved = json.loads(config_path.read_text())
    assert saved["owner_scoping"] is False
    assert saved["include_base_namespace_recall"] is False
    assert saved["include_legacy_actor_namespace_recall"] is True
    assert saved["top_k"] == 7


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


def test_identity_scope_api_returns_config_and_unmapped_namespaces(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "yantrikdb.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (rid TEXT PRIMARY KEY, namespace TEXT)")
        conn.executemany("INSERT INTO memories VALUES (?,?)", [("r1", "owner:person-alpha"), ("r2", "space:team-alpha")])
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", tmp_path / "missing-yantrikdb.json")
    dashboard.save_dashboard_settings({
        "identity_scope": {
            "identities": [{"id": "person-alpha", "label": "Person Alpha", "private_scope": "owner:person-alpha"}],
            "actors": [{"platform": "chat", "actor_id": "actor-alpha", "identity": "person-alpha"}],
            "spaces": [{"id": "team-alpha", "label": "Team Alpha", "scope": "space:team-alpha", "members": ["person-alpha"]}],
            "conversations": [{"platform": "chat", "conversation_id": "room-alpha", "scope": "space:team-alpha"}],
        }
    })

    client = TestClient(dashboard.app)
    response = client.get("/api/identity-scope")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == {"identities": 1, "actors": 1, "spaces": 1, "conversations": 1, "unmapped_namespaces": 0}
    assert data["identity_scope"]["spaces"][0]["scope"] == "space:team-alpha"
    assert data["namespace_inventory"][0] | {"mapped_to": data["namespace_inventory"][0]["mapped_to"]} == data["namespace_inventory"][0]
    assert data["namespace_inventory"][0]["namespace"] == "owner:person-alpha"
    assert data["namespace_inventory"][0]["mapped"] is True
    assert data["namespace_inventory"][0]["mapped_to"] == "Person Alpha"
    assert data["namespace_inventory"][0]["mapping_type"] == "identity"
    assert data["namespace_inventory"][1]["namespace"] == "space:team-alpha"
    assert data["namespace_inventory"][1]["mapped"] is True
    assert data["namespace_inventory"][1]["mapped_to"] == "Team Alpha"
    assert data["namespace_inventory"][1]["mapping_type"] == "shared_scope"


def test_identity_scope_marks_config_covered_namespaces(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "yantrikdb.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (namespace TEXT)")
        conn.executemany("INSERT INTO memories(namespace) VALUES (?)", [
            ("hermes:hermes:default",),
            ("hermes:hermes:default:owner:whatsapp-6590264641-d4754bd8c823",),
        ])

    identity_map_path = tmp_path / "identity-map.json"
    identity_map_path.write_text(json.dumps({
        "owners": {
            "owner:yc": {"actors": ["whatsapp:6590264641"]}
        }
    }))
    config_path = tmp_path / "yantrikdb.json"
    config_path.write_text(json.dumps({
        "mode": "embedded",
        "namespace": "hermes",
        "top_k": "10",
        "owner_scoping": True,
        "include_base_namespace_recall": True,
        "include_legacy_actor_namespace_recall": True,
        "identity_map_path": str(identity_map_path),
    }))
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", config_path)
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")

    payload = dashboard.identity_scope_payload()
    by_ns = {item["namespace"]: item for item in payload["namespace_inventory"]}
    assert by_ns["hermes:hermes:default"]["mapped_to"] == "Shared by all profiles"
    assert by_ns["hermes:hermes:default"]["mapping_type"] == "shared_fallback"
    assert by_ns["hermes:hermes:default"]["derived_by_config"] is True
    legacy = by_ns["hermes:hermes:default:owner:whatsapp-6590264641-d4754bd8c823"]
    assert legacy["mapped_to"] == "Yc via old account bucket"
    assert legacy["mapping_type"] == "legacy_actor_fallback"
    assert payload["runtime_scope"]["owner_scoping"] is True


def test_identity_scope_api_persists_config_when_admin_enabled(tmp_path, monkeypatch):
    db_path = tmp_path / "yantrikdb.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (namespace TEXT)")
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", tmp_path / "missing-yantrikdb.json")
    monkeypatch.setattr(dashboard, "ADMIN_MODE_ENV", True)
    client = TestClient(dashboard.app)
    payload = {
        "identity_scope": {
            "identities": [{"id": "person-beta", "label": "Person Beta", "private_scope": "owner:person-beta"}],
            "actors": [],
            "spaces": [],
            "conversations": [],
        }
    }

    response = client.post("/api/identity-scope", json=payload)

    assert response.status_code == 200
    assert dashboard.load_dashboard_settings()["identity_scope"]["identities"][0]["id"] == "person-beta"


def test_index_has_identity_scope_page_contract():
    html = (Path(dashboard.STATIC_DIR) / "index.html").read_text()
    js = (Path(dashboard.STATIC_DIR) / "app.js").read_text()
    assert 'data-view="identity-scope">Identity &amp; Scope</button>' in html
    assert 'data-view="ops">Maintenance</button>\n      <button class="nav-item" data-view="identity-scope"' in html
    assert 'id="view-identity-scope"' in html
    assert 'id="identityScopeSummary"' in html
    assert 'id="identityScopingStatus"' in html
    assert 'id="ownerScopingToggle"' in html
    assert 'id="includeBaseRecallToggle"' in html
    assert 'id="includeActorRecallToggle"' in html
    assert 'id="saveMemoryScoping"' in html
    assert "top_k" in html
    assert "include_legacy_actor_namespace_recall" in html
    assert "include_base_namespace_recall" in html
    assert "owner_scoping" in html
    assert 'id="identityScopeJson"' in html
    assert 'id="identityForm"' in html
    assert 'id="actorForm"' in html
    assert "Add actor mapping manually" in html
    assert 'id="actorIdentityFilter"' in html
    assert 'id="spaceForm"' in html
    assert 'id="spaceMembersChecklist"' in html
    assert 'id="conversationForm"' in html
    assert '<select id="conversationPlatform"' in html
    assert 'id="conversationIdOptions"' in html
    assert '<h2>Actors</h2><span class="muted">platform accounts</span>' in html
    assert "Create identities to group platform accounts" in html
    assert "Shared spaces" in html
    assert "Chat routing" in html
    assert "who each memory bucket belongs to" in html
    assert "Edit person" in js
    assert "Technical details" in js
    assert "Storage namespace" in js
    assert "actorIdentityFilterOptions" in js
    assert "filteredActors" in js
    assert "inline-identity-select" in js
    assert "data-save-actor-identity" in js
    assert "Identity" in js
    assert "Unassigned" in js
    assert "memory bucket discovery" in js
    assert "checkbox-pill-row" in js
    assert "renderSpaceMemberChecklist" in js
    assert "selectedSpaceMembers" in js
    assert "availablePlatformOptions" in js
    assert "Chat route saved" in js
    assert "Shared space added" in js
    assert "identity-scope" in js
    assert "/api/identity-scope" in js
    assert "addIdentityFromForm" in js
    assert "addActorFromForm" in js
    assert "saveInlineActorIdentity" in js
    assert "addSpaceFromForm" in js
    assert "addConversationFromForm" in js


def test_identity_scope_api_imports_yantrikdb_identity_map(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "yantrikdb.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (rid TEXT PRIMARY KEY, namespace TEXT)")
        conn.executemany("INSERT INTO memories VALUES (?,?)", [("r1", "owner:person-alpha"), ("r2", "hermes:hermes:default:owner:person-alpha")])
    identity_map = tmp_path / "identity-map.json"
    identity_map.write_text('{"owners":{"owner:person-alpha":{"actors":["chat:actor-alpha","telegram:actor-alpha"]}}}')
    config = tmp_path / "yantrikdb.json"
    config.write_text('{"identity_map_path":"' + str(identity_map) + '"}')
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", config)

    data = TestClient(dashboard.app).get("/api/identity-scope").json()

    assert data["summary"]["identities"] == 1
    assert data["summary"]["actors"] == 2
    assert data["identity_scope"]["identities"][0]["id"] == "person-alpha"
    assert {a["platform"] for a in data["identity_scope"]["actors"]} == {"chat", "telegram"}
    assert all(item["mapped"] for item in data["namespace_inventory"])


def test_identity_scope_api_detects_unassigned_actor_from_namespace(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "yantrikdb.db"
    namespace = "hermes:hermes:default:owner:whatsapp-123456789-lid-abcdef123456"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (rid TEXT PRIMARY KEY, namespace TEXT)")
        conn.execute("INSERT INTO memories VALUES (?,?)", ("r1", namespace))
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", tmp_path / "missing-yantrikdb.json")
    monkeypatch.setattr(dashboard, "WHATSAPP_SESSION_DIR", tmp_path / "wa-session")

    data = TestClient(dashboard.app).get("/api/identity-scope").json()

    actor = data["identity_scope"]["actors"][0]
    assert actor["platform"] == "whatsapp"
    assert actor["actor_id"] == "123456789@lid"
    assert actor["identity"] == ""
    assert actor["source"] == "namespace_inventory"
    assert data["namespace_inventory"][0]["mapped"] is False


def test_identity_scope_dashboard_edits_override_imported_identity_map(tmp_path, monkeypatch):
    import sqlite3

    db_path = tmp_path / "yantrikdb.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE memories (rid TEXT PRIMARY KEY, namespace TEXT)")
    identity_map = tmp_path / "identity-map.json"
    identity_map.write_text('{"owners":{"owner:person-alpha":{"actors":["chat:actor-alpha"]}}}')
    config = tmp_path / "yantrikdb.json"
    config.write_text('{"identity_map_path":"' + str(identity_map) + '"}')
    monkeypatch.setattr(dashboard, "DB_PATH", db_path)
    monkeypatch.setattr(dashboard, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(dashboard, "YANTRIKDB_CONFIG_PATH", config)
    dashboard.save_dashboard_settings({"identity_scope": {"identities": [
        {"id": "person-alpha", "label": "Person Alpha Edited", "private_scope": "owner:person-alpha"}
    ], "actors": [], "spaces": [], "conversations": []}})

    data = TestClient(dashboard.app).get("/api/identity-scope").json()

    identity = data["identity_scope"]["identities"][0]
    assert identity["label"] == "Person Alpha Edited"
    assert identity["resolved_scope"].startswith("owner:owner-person-alpha-")
    assert identity["source"] == "dashboard"


def test_visualiser_legend_colours_match_runtime_themes():
    css = Path("static/styles.css").read_text()
    assert "--legend-entity:#ffd6dd" in css
    assert "--legend-memory:orange" in css
    assert "--legend-link:#c6e0ff" in css
    assert "--legend-entity:#66e8c6" in css
    assert "--legend-memory:#ff9b6a" in css
    assert "--legend-link:#52d6b5" in css
    assert "var(--legend-entity)" in css
    assert "var(--legend-memory)" in css
    assert "var(--legend-link)" in css


def test_memory_scoping_controls_auto_save_on_change():
    js = Path("static/app.js").read_text()
    assert "saveMemoryScoping" in js
    assert "saveMemoryScopingSettings({silent:true})" in js
    assert "#ownerScopingToggle" in js
    assert "#includeBaseRecallToggle" in js
    assert "#includeActorRecallToggle" in js
    assert "#topKSetting" in js


def test_sidebar_credit_links_are_present():
    html = Path("static/index.html").read_text()
    assert "Built by" in html
    assert "YantrikDB" in html
    assert "https://github.com/wysie" in html
    assert "https://github.com/spranab" in html
    assert "https://github.com/yantrikos/y" in html
    assert html.count('rel="noopener noreferrer"') >= 3


def test_sidebar_admin_status_is_compact_and_hidden_in_mobile_header():
    html = Path("static/index.html").read_text()
    css_source = Path("src/styles.css").read_text()
    js = Path("static/app.js").read_text()
    assert 'class="admin-status" aria-label="Admin mode status"' in html
    assert "Admin mode disabled" in html
    assert "Toggle writes from Settings." not in html
    assert "<div class=\"label\">Mode</div>" not in html
    assert ".admin-status .pill" in css_source
    assert ".side-card, .admin-status, .sidebar-credit { display: none; }" in css_source
    assert "Admin mode enabled" in js
    assert "Admin mode disabled" in js
    assert "on?'Admin mode enabled':'Admin mode disabled'" in js


def test_identity_scope_status_chips_have_layout_styles():
    css_source = Path("src/styles.css").read_text()
    assert ".scope-status-row" in css_source
    assert ".scope-status" in css_source
    assert "flex-col" in css_source
    assert "text-ellipsis" in css_source
    js = Path("static/app.js").read_text()
    assert "scope-status" in js
    assert "title=\"${esc(key)}\"" in js


def test_memory_status_active_uses_good_not_hot_pill():
    js = Path("static/app.js").read_text()
    assert "function statusPillClass" in js
    assert "v==='active' ? 'good'" in js
    assert "<span class=\"pill ${statusPillClass(m.consolidation_status)}\">" in js
    assert "<span class=\"pill hot\">${esc(statusLabel(m.consolidation_status))}" not in js


def test_readme_documents_hermes_plugin_install_and_no_admin_token():
    readme = Path("README.md").read_text()
    assert "# YantrikDB for Hermes Dashboard" in readme
    assert "hermes plugins install wysie/yantrikdb-hermes-dashboard --enable" in readme
    assert "hermes plugins update yantrikdb-hermes-dashboard" in readme
    assert "There is no admin token to configure" in readme
    assert "Admin Mode" in readme
    assert "Dashboard password" in readme or "dashboard password" in readme


def test_product_metadata_uses_hermes_positioning():
    assert "YantrikDB for Hermes" in Path("static/index.html").read_text()
    assert "YantrikDB for Hermes" in Path("app.py").read_text()
    plugin = Path("plugin.yaml").read_text()
    assert "Hermes Agent memory operations" in plugin
    assert "author: wysie" in plugin


def test_renamed_repo_metadata_uses_new_slug():
    assert "name: yantrikdb-hermes-dashboard" in Path("plugin.yaml").read_text()
    assert 'name = "yantrikdb-hermes-dashboard"' in Path("pyproject.toml").read_text()
    readme = Path("README.md").read_text()
    assert "wysie/yantrikdb-hermes-dashboard" in readme
    assert "~/.hermes/plugins/yantrikdb-hermes-dashboard" in readme
    assert "~/.hermes/plugin-data/yantrikdb-hermes-dashboard/settings.json" in readme
    assert "LEGACY_SETTINGS_PATH" in Path("app.py").read_text()


def test_three_visualiser_inspector_actions_use_button_styles():
    js = Path("static/app.js").read_text()
    assert "const memoryId = overlay ? 'threeOverlayMemory' : 'threeMemory';" in js
    assert "class=\"btn primary tiny\"" in js
    assert "class=\"btn secondary tiny\"" in js
    assert 'id="threeSearch" class="tiny"' not in js


def test_three_visualiser_fullscreen_overlay_is_inside_viewport():
    html = Path("static/index.html").read_text()
    css = Path("src/styles.css").read_text()
    js = Path("static/app.js").read_text()
    assert 'id="threeFullscreenInspector" class="three-fullscreen-inspector"' in html
    assert html.index('id="threeFullscreenInspector"') < html.index('id="threeInspector"')
    assert ".three-viewport:fullscreen .three-fullscreen-inspector.active" in css
    assert "threeOverlayMemory" in js
    assert "threeOverlaySearch" in js
    assert "threeOverlayClose" in js
    assert "three-fullscreen-inspector,.fullscreen-exit,.viewport-fullscreen,.constellation-legend" in js


def test_mobile_app_background_is_fixed_across_tabs():
    css = Path("src/styles.css").read_text()
    assert "@apply m-0 overflow-hidden bg-yan-bg" in css
    assert "background-attachment: fixed;" in css
    assert "background-position: center top;" in css
    assert "background-size: 100vw 100vh;" in css


def test_impeccable_surface_polish_removes_raw_black_and_quiets_mobile_config_keys():
    css = Path("src/styles.css").read_text()
    assert "--surface-35: rgba(13, 13, 22, .35);" in css
    assert "bg-black" not in css
    assert "border-black" not in css
    assert "ring-offset-black" not in css
    assert "input[type=\"checkbox\"] { @apply relative h-5 w-5 min-w-5" in css
    assert "input[type=\"checkbox\"]:checked::after" in css
    assert "@apply absolute left-1/2 top-1/2 h-4 w-4" in css
    assert "clip-path: polygon" in css
    assert ".config-name { @apply mt-1.5 text-[10px]; }" in css
    assert ".scope-status code { @apply mt-1; }" in css
    assert ".config-name { display: none; }" not in css
    assert ".scope-status code { display: none; }" not in css


def test_mobile_scope_and_visualiser_toolbar_css_is_compact():
    css = Path("src/styles.css").read_text()
    assert ".scope-bar select" in css
    assert "appearance: none" in css
    assert "background-position: calc(100% - 15px) 50%" in css
    assert ".visualiser-actions { @apply grid w-full grid-cols-4 gap-2; }" in css
    assert ".visualiser-toolbar .visualiser-actions .btn" in css
    assert "whitespace-normal text-xs leading-5" in css


def test_visualiser_fullscreen_control_lives_in_viewport():
    html = Path("static/index.html").read_text()
    css = Path("src/styles.css").read_text()
    js = Path("static/app.js").read_text()
    assert 'id="threeFullscreen" class="viewport-fullscreen" aria-label="Open visualiser fullscreen"' in html
    assert "function threeRenderPixelRatio(viewport)" in js
    assert "qualityBoost = fullscreen ? 1.45 : 1.35" in js
    assert "renderer.setPixelRatio(threeRenderPixelRatio(viewport));" in js
    assert "canvas.width = 256; canvas.height = 256;" in js
    assert "canvas.width = 1024; canvas.height = 640;" in js
    assert "precision:'highp'" in js
    assert "text-rendering: geometricPrecision" in css
    assert html.index('id="threeFullscreen"') > html.index('id="threeViewport"')
    assert html.index('id="threeFullscreen"') < html.index('id="threeLabels"')
    assert 'id="threeFullscreen" class="btn secondary"' not in html
    assert ".viewport-fullscreen" in css
    assert ".three-viewport:fullscreen .viewport-fullscreen { display: none; }" in css
    assert ".viewport-fullscreen" in js
    assert "Drag to rotate · Pinch to zoom · Pan to move." in html


def test_identity_namespace_coverage_uses_mobile_cards():
    js = Path("static/app.js").read_text()
    assert "namespace-coverage-list" in js
    assert "namespace-coverage-card" in js
    assert "coverage-status" in js
    assert "<table><thead><tr><th>Namespace</th><th>Rows</th><th>Belongs to</th><th>Status</th>" not in js
    css = Path("src/styles.css").read_text()
    assert ".namespace-coverage-head { @apply grid" in css
    assert ".coverage-status" in css
    assert "whitespace-normal" in css


def test_identity_namespace_coverage_does_not_use_table_wrapper_border():
    html = Path("static/index.html").read_text()
    assert 'id="identityNamespaceTable" class="coverage-wrap"' in html
    assert 'id="identityNamespaceTable" class="table-wrap"' not in html
    css = Path("src/styles.css").read_text()
    assert ".coverage-wrap { @apply max-w-full overflow-visible rounded-none border-0 bg-transparent; }" in css


def test_mobile_memory_browser_filters_are_compact():
    html = Path("static/index.html").read_text()
    css = Path("src/styles.css").read_text()
    js = Path("static/app.js").read_text()
    assert 'class="toolbar memory-toolbar"' in html
    assert 'id="memoryAdvancedFilters" class="memory-advanced"' in html
    assert "More filters" in html
    assert '<button id="memoryApply" class="btn secondary">Apply</button>' in html
    assert '<button id="memoryReset" class="btn ghost">Reset</button>' in html
    assert ".memory-toolbar #memoryNamespaceFilter { display: none; }" in css
    assert ".memory-toolbar #memorySearch { @apply col-span-2 min-h-10; }" in css
    assert ".memory-filter-actions { @apply grid grid-cols-2 gap-2; }" in css
    assert "function updateMemoryAdvancedFilters()" in js
    assert "details.open = hasAdvanced" in js


def test_readme_documents_mock_screenshot_gallery():
    readme = Path("README.md").read_text()
    assert "## Screenshots" in readme
    assert "synthetic mock YantrikDB database" in readme
    assert "docs/screenshots/desktop-overview.png" in readme
    assert "docs/screenshots/mobile-identity-scope.png" in readme
    assert "docs/screenshots/mobile-settings.png" in readme
    assert "python3 scripts/generate_mock_screenshots.py" in readme


def test_mock_screenshot_generator_avoids_private_db_paths():
    script = Path("scripts/generate_mock_screenshots.py").read_text()
    assert "never reads the user's real YantrikDB memory store" in script
    assert "/Users/wysie/.hermes/yantrikdb-memory.db" not in script
    assert "mock-yantrikdb.db" in script
