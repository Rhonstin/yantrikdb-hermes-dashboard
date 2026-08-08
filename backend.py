"""HTTP backend for cluster-mode deployments (Rhonstin/opencode fork).

The dashboard's default mode reads the embedded-mode SQLite store at
``YANTRIKDB_DB_PATH`` directly. That works for single-instance
deployments but locks out anyone running yantrikdb-server on an HA
cluster — there's no local SQLite file to read.

Setting ``YANTRIKDB_SERVER_URL`` switches the dashboard to HTTP mode:
every supported route proxies to the matching ``/v1/*`` endpoint on the
cluster. Auth is the same Bearer-token scheme used by the MCP client.

This fork adds proxy support for the full endpoint set exposed by the
Rhonstin yantrikdb-server fork: recall, conflicts + resolve, think,
entities, graph, stale, upcoming, patterns, triggers (+ lifecycle),
export, sessions, skills, and identity-scope.
"""
from __future__ import annotations

import os
from typing import Any

import requests
from fastapi import HTTPException

DEFAULT_TIMEOUT = (3.0, 15.0)  # (connect, read)


class NotImplementedHTTPBackend(Exception):
    """Raised when a route has no HTTP equivalent yet."""


class HTTPBackend:
    """Thin proxy to a yantrikdb-server cluster."""

    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = base_url.split(",")[0].strip().rstrip("/")
        self.token = token.strip()
        self._session = requests.Session()
        if self.token:
            self._session.headers["Authorization"] = f"Bearer {self.token}"

    # ----- HTTP plumbing -----

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._session.request(
                method,
                url,
                params=params,
                json=json,
                timeout=DEFAULT_TIMEOUT,
            )
        except requests.RequestException as e:
            raise HTTPException(502, f"yantrikdb-server unreachable: {e}") from e
        if resp.status_code == 404:
            raise HTTPException(
                501,
                f"server route {path} not found "
                "(needs the Rhonstin yantrikdb-server fork with dashboard endpoints)",
            )
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("error", {}).get("message") or body.get("detail") or resp.text
            except ValueError:
                msg = resp.text
            raise HTTPException(resp.status_code, f"yantrikdb-server: {msg}")
        if resp.status_code == 204 or not resp.content:
            return {}
        ctype = resp.headers.get("Content-Type", "")
        if "jsonl" in ctype or "ndjson" in ctype or ctype == "application/x-ndjson":
            return resp.text
        if "json" in ctype:
            try:
                return resp.json()
            except ValueError as e:
                raise HTTPException(502, f"non-JSON response from {path}: {e}") from e
        return resp.text

    # ----- Supported routes -----

    def health(self, *, base_namespace: str = "", default_namespace: str = "") -> dict[str, Any]:
        body = self._request("GET", "/v1/health")
        cluster = body.get("cluster") or {}
        return {
            "ok": body.get("status") == "ok" or cluster.get("healthy") is True,
            "mode": "http",
            "server_url": self.base_url,
            "db_path": None,
            "db_exists": True,
            "db_size_bytes": 0,
            "yantrikdb_version": body.get("version") or "0.8.17+",
            "cluster": cluster,
            "engines_loaded": body.get("engines_loaded"),
            "base_namespace": base_namespace,
            "default_namespace": default_namespace,
            "namespaces": [],
        }

    def stats(self, namespace: str) -> dict[str, Any]:
        body = self._request("GET", "/v1/stats", params={"namespace": namespace})
        return {
            "namespace": namespace,
            "memory_status": [],
            "by_domain": [],
            "by_source": [],
            "by_type": [],
            "recent_by_day": [],
            "open_conflicts": body.get("open_conflicts") or 0,
            "entities": body.get("entities") or 0,
            "edges": body.get("edges") or 0,
            "engine": body,
        }

    def list_memories(
        self,
        *,
        namespace: str,
        status: str = "active",
        domain: str = "",
        source: str = "",
        memory_type: str = "",
        q: str = "",
        limit: int = 50,
        offset: int = 0,
        sort: str = "created_at",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "namespace": namespace,
            "status": status,
            "limit": limit,
            "offset": offset,
            "sort": sort,
        }
        if domain:
            params["domain"] = domain
        if source:
            params["source"] = source
        if memory_type:
            params["memory_type"] = memory_type
        if q:
            params["q"] = q
        return self._request("GET", "/v1/memories", params=params)

    def get_memory(self, rid: str, namespace: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/memory/{rid}", params={"namespace": namespace})

    def recall(self, *, query: str, top_k: int = 10, namespace: str = "",
               domain: str | None = None, source: str | None = None,
               include_consolidated: bool = False,
               expand_entities: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
            "include_consolidated": include_consolidated,
            "expand_entities": expand_entities,
        }
        if namespace:
            payload["namespace"] = namespace
        if domain:
            payload["domain"] = domain
        if source:
            payload["source"] = source
        return self._request("POST", "/v1/recall", json=payload)

    def conflicts(self, *, namespace: str = "", status: str = "",
                  limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if namespace:
            params["namespace"] = namespace
        if status:
            params["status"] = status
        body = self._request("GET", "/v1/conflicts", params=params)
        # server returns {"conflicts": [...]}; dashboard expects {"items": [...]}
        return {"items": body.get("conflicts") or []}

    def conflict_detail(self, conflict_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/v1/conflicts/{conflict_id}")
        return {"conflict": body}

    def resolve_conflict(self, conflict_id: str, strategy: str, *,
                         winner_rid: str | None = None,
                         new_text: str | None = None,
                         resolution_note: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"strategy": strategy}
        if winner_rid:
            payload["winner_rid"] = winner_rid
        if new_text:
            payload["new_text"] = new_text
        if resolution_note:
            payload["resolution_note"] = resolution_note
        return self._request("POST", f"/v1/conflicts/{conflict_id}/resolve", json=payload)

    def think(self, **cfg: Any) -> dict[str, Any]:
        return self._request("POST", "/v1/think", json=cfg)

    def identity_scope(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return self._request("GET", "/v1/identity-scope")

    def entities(self, *, q: str = "", limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if q:
            params["q"] = q
        return self._request("GET", "/v1/entities", params=params)

    def graph(self, entity: str, *, namespace: str = "") -> dict[str, Any]:
        params: dict[str, Any] = {}
        if namespace:
            params["namespace"] = namespace
        return self._request("GET", f"/v1/graph/{entity}", params=params)

    def stale(self, *, namespace: str = "", days: float = 30.0,
              limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"days": days, "limit": limit}
        if namespace:
            params["namespace"] = namespace
        return self._request("GET", "/v1/stale", params=params)

    def upcoming(self, *, namespace: str = "", days: float = 7.0,
                 limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"days": days, "limit": limit}
        if namespace:
            params["namespace"] = namespace
        return self._request("GET", "/v1/upcoming", params=params)

    def sessions(self, *, namespace: str = "", client_id: str = "",
                 limit: int = 50) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if namespace:
            params["namespace"] = namespace
        if client_id:
            params["client_id"] = client_id
        return self._request("GET", "/v1/sessions", params=params)

    def patterns(self, *, limit: int = 50) -> dict[str, Any]:
        return self._request("GET", "/v1/patterns", params={"limit": limit})

    def triggers(self, *, limit: int = 50, status: str = "") -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        return self._request("GET", "/v1/triggers", params=params)

    def trigger_acknowledge(self, trigger_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/triggers/{trigger_id}/acknowledge")

    def trigger_dismiss(self, trigger_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/triggers/{trigger_id}/dismiss")

    def trigger_act(self, trigger_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/triggers/{trigger_id}/act")

    def export_memories(self, *, namespace: str = "", limit: int = 100000,
                        offset: int = 0) -> str:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if namespace:
            params["namespace"] = namespace
        raw = self._request("GET", "/v1/export/memories.jsonl", params=params)
        return raw if isinstance(raw, str) else ""

    def forget(self, rid: str, *, namespace: str = "", reason: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"rid": rid}
        if namespace:
            payload["namespace"] = namespace
        if reason:
            payload["reason"] = reason
        return self._request("POST", "/v1/forget", json=payload)

    def skill_search(self, query: str, top_k: int = 10,
                     applies_to: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if applies_to:
            payload["applies_to"] = [applies_to]
        return self._request("POST", "/v1/skills/search", json=payload)

    def skill_outcomes(self, skill_id: str, limit: int = 25) -> dict[str, Any]:
        body = self._request("GET", f"/v1/skills/{skill_id}/outcome",
                             params={"limit": limit})
        if isinstance(body, dict) and "items" not in body:
            # Server may return raw rows; wrap in the dashboard's shape.
            return {"items": body.get("outcomes") or body.get("results") or [], "total": len(body.get("outcomes") or body.get("results") or []), "skill_id": skill_id}
        return body


class HTTPBackendSkillSearch:
    """Minimal shim so app.skill_backend() can run in HTTP mode.

    Provides the ``skill_search(query, top_k=, applies_to=)`` interface
    the dashboard expects, proxying to the server's /v1/skills/search.
    """

    def __init__(self, backend: HTTPBackend) -> None:
        self._backend = backend

    def skill_search(self, query: str, top_k: int = 10,
                     applies_to: str | None = None) -> dict[str, Any]:
        return self._backend.skill_search(query, top_k=top_k, applies_to=applies_to)


def make_backend() -> HTTPBackend | None:
    """Return an HTTPBackend if YANTRIKDB_SERVER_URL is set, else None."""
    url = os.environ.get("YANTRIKDB_SERVER_URL", "").strip()
    if not url:
        return None
    token = os.environ.get("YANTRIKDB_TOKEN", "").strip()
    return HTTPBackend(base_url=url, token=token)


def not_implemented_response(feature: str) -> HTTPException:
    return HTTPException(
        501,
        f"{feature} is not implemented in HTTP mode. "
        "The Rhonstin dashboard fork proxies this endpoint — check "
        "YANTRIKDB_SERVER_URL and that the server fork is deployed.",
    )
