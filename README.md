# YantrikDB Dashboard

A polished, local-first web dashboard for inspecting a YantrikDB memory database.

It is designed for private agent-memory operations: recall debugging, contradiction review, memory browsing, namespace checks, entity/graph inspection, decay signals, and read-only visualisation.

## Highlights

- Local-only FastAPI app with a static HTML/CSS/JS frontend
- Read-only by default; mutation endpoints require an explicit admin token
- Memory browser with search, filters, card grid, and detail drawer
- Recall debugger with optional domain/source filters
- Contradiction, entity graph, stale/upcoming, trigger, and pattern views
- 3D memory visualiser powered by local data only
- JSONL export for active memories
- No external API calls from the dashboard backend

## Safety model

The dashboard can expose sensitive memory content to whoever can reach the web UI. Bind it to `127.0.0.1` unless you intentionally want LAN access.

Admin/mutating endpoints are disabled unless `YANTRIKDB_DASHBOARD_ADMIN_TOKEN` is set. When enabled, requests must include the same value in the `X-Admin-Token` header.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

You also need access to a YantrikDB SQLite database. By default the app looks for:

```text
~/.hermes/yantrikdb-memory.db
```

Override it with `YANTRIKDB_DB_PATH`.

## Run

```bash
YANTRIKDB_DASHBOARD_HOST=127.0.0.1 \
YANTRIKDB_DASHBOARD_PORT=8767 \
YANTRIKDB_DB_PATH=~/.hermes/yantrikdb-memory.db \
python app.py
```

Then open:

```text
http://127.0.0.1:8767
```

You can also use the helper script:

```bash
scripts/start.sh
```

## Frontend styling

The dashboard uses a local Tailwind build, not the Tailwind CDN.

```bash
npm install
npm run build:css
```

Source styles live in `src/styles.css`; the compiled artifact is served from `static/styles.css` so the FastAPI/launchd runtime stays a simple static app.

## macOS launchd service

For a persistent local dashboard that starts on login and restarts after crashes, install the LaunchAgent:

```bash
YANTRIKDB_DASHBOARD_PYTHON=/absolute/path/to/python \
YANTRIKDB_DASHBOARD_HOST=0.0.0.0 \
YANTRIKDB_DASHBOARD_PORT=8767 \
scripts/install-launchd.sh
```

The installer writes:

```text
~/Library/LaunchAgents/io.yantrikdb.dashboard.local.plist
```

It uses `RunAtLoad` plus `KeepAlive` with `SuccessfulExit=false`, so launchd restarts the dashboard if it crashes. Logs go to `.run/launchd.out.log` and `.run/launchd.err.log` by default.

Uninstall:

```bash
scripts/uninstall-launchd.sh
```

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `YANTRIKDB_DASHBOARD_HOST` | `0.0.0.0` | Bind host for Uvicorn |
| `YANTRIKDB_DASHBOARD_PORT` | `8767` | Bind port for Uvicorn |
| `YANTRIKDB_DB_PATH` | `~/.hermes/yantrikdb-memory.db` | SQLite DB path |
| `YANTRIKDB_NAMESPACE` | `hermes` | Base namespace used for defaults |
| `YANTRIKDB_DASHBOARD_NAMESPACE` | `${YANTRIKDB_NAMESPACE}:hermes:default` | Default namespace selected in UI/API |
| `YANTRIKDB_EMBEDDING_DIM` | inferred from DB | Override embedding dimension |
| `YANTRIKDB_EMBEDDER` | dimension-based default | Override embedder name |
| `YANTRIKDB_DASHBOARD_ADMIN_TOKEN` | unset | Enables admin mutations when set |
| `YANTRIKDB_DASHBOARD_PYTHON` | `python3` | Python binary used by `scripts/start.sh` and `scripts/install-launchd.sh` |
| `YANTRIKDB_DASHBOARD_LOG_DIR` | `.run` | launchd stdout/stderr directory |
| `YANTRIKDB_DASHBOARD_LAUNCHD_LABEL` | `io.yantrikdb.dashboard.local` | macOS LaunchAgent label |

## Admin endpoints

Admin operations include conflict resolution, `think()`, and forgetting memories. They remain unavailable until you set an admin token:

```bash
export YANTRIKDB_DASHBOARD_ADMIN_TOKEN='choose-a-local-secret'
```

Then enter that token in the dashboard's Admin Token field or send it as `X-Admin-Token`.

## Development

```bash
python -m py_compile app.py
node --check static/app.js
python -m pytest
```

The tests avoid requiring a real YantrikDB database for basic smoke coverage.

## Repository hygiene

This repo intentionally excludes:

- local SQLite databases
- logs and process files
- virtual environments
- caches
- private `.env` files

Do not commit memory exports, live database snapshots, or screenshots containing private memory content.

## License

MIT
