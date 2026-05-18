#!/usr/bin/env python3
"""Generate mock-data screenshots for the README gallery.

This script intentionally builds a temporary synthetic YantrikDB SQLite database.
It never reads the user's real YantrikDB memory store.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    import websocket
except ImportError as exc:  # pragma: no cover - optional local utility
    raise SystemExit("websocket-client is required to generate screenshots") from exc

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "screenshots"
TMP_DIR = Path("/tmp/yantrikdb-hermes-dashboard-screenshots")
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
DEFAULT_NS = "hermes:hermes:default"
YC_NS = "hermes:hermes:default:owner:owner-yc-fba6a927a29b"
TEAM_NS = "hermes:hermes:default:owner:group-household-8f7c2e4a1c09"
OLD_NS = "hermes:hermes:default:owner:whatsapp-6590000000-7ca11f3b2d88"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_mock_config(config_path: Path, identity_path: Path) -> None:
    identity_path.write_text(json.dumps({
        "owners": {
            "owner:yc": {"actors": ["whatsapp:6590000000", "telegram:17847389"]},
            "owner:household": {"actors": ["whatsapp:6591111111", "whatsapp:6592222222"]},
        }
    }, indent=2), encoding="utf-8")
    config_path.write_text(json.dumps({
        "mode": "embedded",
        "namespace": "hermes",
        "top_k": 10,
        "owner_scoping": True,
        "include_base_namespace_recall": True,
        "include_legacy_actor_namespace_recall": True,
        "identity_map_path": str(identity_path),
    }, indent=2), encoding="utf-8")


def make_mock_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE memories (
        rid TEXT PRIMARY KEY,
        type TEXT NOT NULL DEFAULT 'semantic',
        text TEXT NOT NULL,
        embedding BLOB,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        importance REAL NOT NULL DEFAULT 0.5,
        half_life REAL NOT NULL DEFAULT 604800,
        last_access REAL NOT NULL,
        access_count INTEGER NOT NULL DEFAULT 0,
        valence REAL NOT NULL DEFAULT 0,
        consolidated_into TEXT,
        consolidation_status TEXT DEFAULT 'active',
        storage_tier TEXT NOT NULL DEFAULT 'hot',
        metadata TEXT DEFAULT '{}',
        namespace TEXT NOT NULL DEFAULT 'default',
        certainty REAL NOT NULL DEFAULT 0.8,
        domain TEXT NOT NULL DEFAULT 'general',
        source TEXT NOT NULL DEFAULT 'user',
        emotional_state TEXT,
        session_id TEXT,
        due_at REAL,
        temporal_kind TEXT,
        tombstone_reason TEXT,
        created_at_unix_micros INTEGER NOT NULL DEFAULT 0,
        embedding_model TEXT,
        prior_rid TEXT,
        resolution_kind TEXT,
        dismissal_reason TEXT,
        confidence_at_write REAL
    );
    CREATE VIRTUAL TABLE memories_fts USING fts5(text, content='memories', content_rowid='rowid');
    CREATE TABLE conflicts (
        conflict_id TEXT PRIMARY KEY, conflict_type TEXT NOT NULL, priority TEXT NOT NULL DEFAULT 'medium',
        status TEXT NOT NULL DEFAULT 'open', memory_a TEXT NOT NULL, memory_b TEXT NOT NULL,
        entity TEXT, rel_type TEXT, detected_at REAL NOT NULL, detected_by TEXT NOT NULL,
        detection_reason TEXT NOT NULL, resolved_at REAL, resolved_by TEXT, strategy TEXT,
        winner_rid TEXT, resolution_note TEXT, hlc BLOB NOT NULL, origin_actor TEXT NOT NULL
    );
    CREATE TABLE entities (name TEXT PRIMARY KEY, entity_type TEXT DEFAULT 'concept', first_seen REAL NOT NULL, last_seen REAL NOT NULL, mention_count INTEGER NOT NULL DEFAULT 1, metadata TEXT DEFAULT '{}');
    CREATE TABLE memory_entities (memory_rid TEXT NOT NULL, entity_name TEXT NOT NULL, PRIMARY KEY(memory_rid, entity_name));
    CREATE TABLE claims (
        claim_id TEXT PRIMARY KEY, src TEXT NOT NULL, dst TEXT NOT NULL, rel_type TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 1.0, created_at REAL NOT NULL, tombstoned INTEGER NOT NULL DEFAULT 0,
        polarity INTEGER NOT NULL DEFAULT 1, modality TEXT NOT NULL DEFAULT 'asserted', valid_from REAL,
        valid_to REAL, extractor TEXT NOT NULL DEFAULT 'mock', extractor_version TEXT, confidence_band TEXT NOT NULL DEFAULT 'high',
        source_memory_rid TEXT, span_start INTEGER, span_end INTEGER, namespace TEXT NOT NULL DEFAULT 'default'
    );
    CREATE VIEW edges AS SELECT claim_id AS edge_id, src, dst, rel_type, weight, created_at, tombstoned,
        polarity, modality, valid_from, valid_to, extractor, extractor_version, confidence_band,
        source_memory_rid, span_start, span_end, namespace FROM claims;
    CREATE INDEX idx_memories_namespace ON memories(namespace);
    CREATE INDEX idx_memories_status ON memories(consolidation_status);
    CREATE INDEX idx_memories_domain ON memories(domain);
    CREATE INDEX idx_memories_source ON memories(source);
    """)
    now = time.time()
    domains = ["memory", "dashboard", "privacy", "automation", "family", "business", "home", "health"]
    snippets = [
        "YantrikDB dashboard should keep memory scope visible, compact, and safe on mobile.",
        "Identity & Scope explains which owner bucket each memory namespace belongs to.",
        "Visualiser controls work best as compact mobile action grids, not vertical button towers.",
        "Local-only WhatsApp memory content must stay on the private machine and never leave the LAN.",
        "Dashboard settings should pair human labels with quiet raw config keys for operator trust.",
        "Recall debugger should show why a memory was retrieved and which namespace it came from.",
        "Namespace coverage cards avoid table overflow and keep status pills readable on phones.",
        "Lifecycle review highlights stale memories, reminders, patterns, and maintenance actions.",
        "Hermes plugin installs should use managed commands, with manual clone as a dev fallback.",
        "Visualiser legends must match the actual runtime colours for entity, memory, and link nodes.",
        "Public screenshots must use synthetic mock data, not private memory content.",
        "Dashboard polish reserves red for destructive or critical states, not normal active memory.",
    ]
    rows = []
    for i in range(96):
        ns = [YC_NS, DEFAULT_NS, TEAM_NS, OLD_NS][i % 4]
        domain = domains[i % len(domains)]
        status = "consolidated" if i % 13 == 0 else ("tombstoned" if i % 29 == 0 else "active")
        text = f"{snippets[i % len(snippets)]} Mock note {i+1}: {domain} operations use readable cards, source badges, and provenance."
        rid = f"mock-{i+1:03d}"
        created = now - i * 7200
        rows.append((rid, "semantic" if i % 3 else "episodic", text, sqlite3.Binary(b"\x00" * 2048), created, created, 0.55 + (i % 9) * 0.045, 604800, created + 300, i % 17, 0, None, status, "hot", json.dumps({"mock": True, "topic": domain}), ns, 0.72 + (i % 5) * 0.045, domain, ["user", "system", "dashboard", "import"][i % 4], None, f"mock-session-{i%6}", None, None, None, int(created * 1_000_000), "potion-base-32M", None, None, None, None))
    con.executemany("""
        INSERT INTO memories(rid,type,text,embedding,created_at,updated_at,importance,half_life,last_access,access_count,valence,
        consolidated_into,consolidation_status,storage_tier,metadata,namespace,certainty,domain,source,emotional_state,session_id,
        due_at,temporal_kind,tombstone_reason,created_at_unix_micros,embedding_model,prior_rid,resolution_kind,dismissal_reason,confidence_at_write)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, rows)
    con.execute("INSERT INTO memories_fts(rowid, text) SELECT rowid, text FROM memories")
    entities = [("YantrikDB", "system"), ("Hermes", "agent"), ("Memory Scope", "concept"), ("Identity Map", "config"), ("Visualiser", "feature"), ("Dashboard", "product")]
    for name, typ in entities:
        con.execute("INSERT INTO entities VALUES (?,?,?,?,?,?)", (name, typ, now-90000, now, 18, json.dumps({"mock": True})))
    for idx, rid in enumerate([r[0] for r in rows[:36]]):
        for ent in [entities[idx % len(entities)][0], entities[(idx+2) % len(entities)][0]]:
            con.execute("INSERT OR IGNORE INTO memory_entities VALUES (?,?)", (rid, ent))
    claims = [("YantrikDB", "powers", "Hermes"), ("Memory Scope", "protects", "Dashboard"), ("Identity Map", "routes", "Memory Scope"), ("Visualiser", "summarises", "YantrikDB"), ("Dashboard", "inspects", "Hermes")]
    for i, (src, rel, dst) in enumerate(claims):
        con.execute("INSERT INTO claims(claim_id,src,dst,rel_type,weight,created_at,source_memory_rid,namespace) VALUES (?,?,?,?,?,?,?,?)", (f"claim-{i+1}", src, dst, rel, 0.82, now-i*5000, f"mock-{i+1:03d}", DEFAULT_NS))
    con.execute("INSERT INTO conflicts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ("conflict-001", "preference", "high", "open", "mock-001", "mock-002", "Dashboard", "prefers", now-8000, "mock", "Two UI density preferences need review", None, None, None, None, None, b"mock", "mock"))
    con.commit()
    con.close()


class ChromeSession:
    def __init__(self, port: int, url: str, width: int, height: int, mobile: bool) -> None:
        self.port, self.url, self.width, self.height, self.mobile = port, url, width, height, mobile
        self.proc: subprocess.Popen[bytes] | None = None
        self.ws: websocket.WebSocket | None = None
        self.counter = 0
        self.profile = TMP_DIR / f"chrome-profile-{port}"

    def __enter__(self) -> "ChromeSession":
        if not CHROME.exists():
            raise SystemExit(f"Chrome not found at {CHROME}")
        self.profile.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen([
            str(CHROME), "--headless=new", "--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist",
            "--no-first-run", "--no-default-browser-check",
            f"--user-data-dir={self.profile}", f"--remote-debugging-port={self.port}", "--remote-allow-origins=*",
            f"--window-size={self.width},{self.height}", self.url,
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 20
        tabs: list[dict[str, Any]] = []
        while time.time() < deadline:
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=1))
                if tabs:
                    break
            except Exception:
                time.sleep(0.2)
        tab = next(tab for tab in tabs if tab.get("type") == "page")
        self.ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=10)
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("Emulation.setDeviceMetricsOverride", {"width": self.width, "height": self.height, "deviceScaleFactor": 2 if self.mobile else 1, "mobile": self.mobile})
        return self

    def __exit__(self, *exc: object) -> None:
        if self.ws:
            self.ws.close()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.ws is None:
            raise RuntimeError("Chrome session not started")
        self.counter += 1
        self.ws.send(json.dumps({"id": self.counter, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.counter:
                return msg

    def prepare(self, view: str) -> dict[str, Any]:
        self.call("Page.navigate", {"url": f"{self.url}?view={view}"})
        self.call("Page.loadEventFired")
        expr = f"""
        (async()=>{{
          for (let i=0; i<120 && typeof setView !== 'function'; i++) await new Promise(r=>setTimeout(r,100));
          if (typeof setView !== 'function') throw new Error('dashboard JS did not initialise');
          setView({json.dumps(view)}, {{replace:true}});
          await new Promise(r=>setTimeout(r,1200));
          if ({json.dumps(view)} === 'memories') {{
            document.querySelector('#memorySearch').value = 'dashboard';
            document.querySelector('#statusFilter').value = 'all';
            await loadMemories();
          }}
          if ({json.dumps(view)} === 'recall') {{
            document.querySelector('#recallQuery').value = 'Why keep memory scope visible?';
            await runRecall();
          }}
          if ({json.dumps(view)} === 'graph') {{
            document.querySelector('#graphEntity').value = 'YantrikDB';
            await loadGraph('YantrikDB');
          }}
          if ({json.dumps(view)} === 'visualiser') {{
            await loadVisualiser(true);
            await new Promise(r=>setTimeout(r,2200));
          }}
          if ({json.dumps(view)} === 'identity-scope') {{
            await loadIdentityScope();
          }}
          if ({json.dumps(view)} === 'settings') {{
            await loadSettings();
          }}
          await new Promise(r=>setTimeout(r,500));
          window.scrollTo(0,0);
          const doc = document.documentElement;
          return {{scrollWidth: doc.scrollWidth, clientWidth: doc.clientWidth, title: document.title}};
        }})()
        """
        res = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True, "returnByValue": True})
        result = res.get("result", {}).get("result", {})
        if result.get("subtype") == "error":
            raise RuntimeError(result.get("description") or result.get("value") or "browser evaluation failed")
        return result.get("value", {})

    def screenshot(self, path: Path) -> None:
        data = self.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})["result"]["data"]
        path.write_bytes(base64.b64decode(data))


def wait_for_server(url: str) -> None:
    deadline = time.time() + 25
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become ready: {url}")


def run() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    db_path = TMP_DIR / "mock-yantrikdb.db"
    settings_path = TMP_DIR / "settings.json"
    config_path = TMP_DIR / "yantrikdb.json"
    identity_path = TMP_DIR / "identity-map.json"
    make_mock_db(db_path)
    make_mock_config(config_path, identity_path)
    if settings_path.exists():
        settings_path.unlink()
    port = free_port()
    base_url = f"http://127.0.0.1:{port}/"
    env = {
        **os.environ,
        "YANTRIKDB_DB_PATH": str(db_path),
        "YANTRIKDB_DASHBOARD_HOST": "127.0.0.1",
        "YANTRIKDB_DASHBOARD_PORT": str(port),
        "YANTRIKDB_DASHBOARD_SETTINGS_PATH": str(settings_path),
        "YANTRIKDB_CONFIG_PATH": str(config_path),
        "HERMES_WHATSAPP_SESSION_DIR": str(TMP_DIR / "whatsapp-session"),
        "YANTRIKDB_EMBEDDER": "potion-base-32M",
        "YANTRIKDB_EMBEDDING_DIM": "512",
    }
    server = subprocess.Popen([sys.executable, str(ROOT / "app.py")], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    try:
        wait_for_server(f"{base_url}api/health")
        shots = [
            ("desktop-overview.png", 1440, 1000, False, "overview"),
            ("desktop-visualiser.png", 1440, 1000, False, "visualiser"),
            ("desktop-memories.png", 1440, 1000, False, "memories"),
            ("desktop-identity-scope.png", 1440, 1000, False, "identity-scope"),
            ("desktop-settings.png", 1440, 1000, False, "settings"),
            ("mobile-overview.png", 390, 844, True, "overview"),
            ("mobile-visualiser.png", 390, 844, True, "visualiser"),
            ("mobile-identity-scope.png", 390, 844, True, "identity-scope"),
            ("mobile-memories.png", 390, 844, True, "memories"),
            ("mobile-settings.png", 390, 844, True, "settings"),
        ]
        manifest: list[dict[str, Any]] = []
        for idx, (name, width, height, mobile, view) in enumerate(shots):
            with ChromeSession(9530 + idx, base_url, width, height, mobile) as chrome:
                metrics = chrome.prepare(view)
                out = OUT_DIR / name
                chrome.screenshot(out)
                manifest.append({"file": name, "view": view, "viewport": f"{width}x{height}", **metrics})
                print(f"wrote {out.relative_to(ROOT)}")
        (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    run()
