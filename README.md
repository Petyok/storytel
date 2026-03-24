# Dark fantasy — stateful AI story (FastAPI + React + JSON + llama.cpp)

Turn-based loop: load `sessions/{id}/*.json` → compact prompt to a local LLM → strict JSON (`scene`, `choices`, `effects_hint`) → deterministic engine updates → save all files.

## Layout

- `backend/` — FastAPI app (`app.main:app`)
- `frontend/` — React + Vite UI
- `sessions/{id}/` — **source of truth**
  - `history.json` — `messages[]`, `pending_scene`, `pending_choices`
  - `inventory.json` — list of `{name, quantity, description?, ...}`
  - `main_character.json` — `name`, `hp` (or legacy `health`), `gold`, `status`, `flags`, …
  - `quests.json` — list with `status`: `active` | `completed` | `failed`
  - `world.json` — `location`, `danger_level`, `time`, `secrets`, `npcs[]`, `ascii_map`, `turn`

Legacy `world.json` from `storyteller_v2.py` (`{ "Setting": {"value": "..."} }`) is still read; new sessions use the flat canonical shape.

## Requirements

- Python 3.10+
- Node 18+ (for Vite)
- llama.cpp **HTTP server** (e.g. `llama-server`) on a port **other than** the API (default API: `8000`, default LLM URL: `http://127.0.0.1:8080`)

## Install (one script)

From the repo root:

```bash
chmod +x install.sh
./install.sh
```

This creates `.venv`, installs `backend/requirements.txt`, and runs `npm install` in `frontend/`. To use system Python instead of a venv: `./install.sh --system`.

## Run (one script)

After install:

```bash
chmod +x run.sh
./run.sh
```

Starts **uvicorn** on port `8000` (background) and **Vite** on `5173` (foreground). Press **Ctrl+C** to stop both.

- Use system Python: `./run.sh --system` (requires dependencies on `PATH`).
- Change ports: `API_PORT=9000 FRONTEND_PORT=5174 ./run.sh` — if you change `API_PORT`, update the `proxy` target in `frontend/vite.config.js` to match.

## Backend

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

(If you used `./install.sh --system`, use `python3 -m uvicorn` instead of `../.venv/bin/python -m uvicorn`.)

Environment (optional):

| Variable | Default | Meaning |
|----------|---------|---------|
| `SESSIONS_DIR` | `<repo>/sessions` | Session root |
| `LLAMA_CPP_URL` | `http://127.0.0.1:8080` | llama.cpp base URL |
| `LLAMA_COMPLETION_PATH` | `/completion` | Completion route |
| `LLM_TIMEOUT_SEC` | `120` | HTTP timeout |
| `MAX_PROMPT_CHARS` | `12000` | Hard cap on assembled prompt |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,...` | Browser origins |

Endpoints:

- `GET /health`
- `GET /sessions` — list session folder names
- `POST /sessions` — body `{"session_id":"my_save","overwrite":false}` → create (or reset with `overwrite: true`), returns same shape as `GET /session/{id}`; `409` if exists and not overwriting
- `GET /session/{id}` — merged state + last scene + pending choices
- `POST /session/{id}/action` — body `{"choice":"..."}` → new scene, choices, updated state (auto-saves JSON)

## llama.cpp (HTTP)

Example (adjust model path and port):

```bash
./llama-server -m /path/to/model.gguf -c 4096 --host 127.0.0.1 --port 8080
```

If your server runs elsewhere:

```bash
export LLAMA_CPP_URL=http://127.0.0.1:YOUR_PORT
```

The client posts JSON to `{LLAMA_CPP_URL}{LLAMA_COMPLETION_PATH}` with `prompt`, `n_predict`, `temperature`, etc., and reads `content` from the response.

## Frontend

After `./install.sh`:

```bash
cd frontend
npm run dev
```

Open the printed URL (default `http://127.0.0.1:5173`). Vite proxies `/session`, `/sessions`, and `/health` to `http://127.0.0.1:8000`.

- Pick a session from the dropdown or type a new id and press **Enter**, then **Reload** if the folder was just created.
- Demo session: `sessions/demo/` (pre-filled state).

## `effects_hint` (engine tags)

The model may include machine-oriented tags in `effects_hint`, separated by `|`, `;`, or newlines:

- `hp+5` / `hp-3`
- `gold+2` / `gold-1`
- `danger+1` / `danger-1`
- `time+1` (advances internal clock)
- `flag:some_flag`
- `item+:Name` / `item-:name`
- `trust:NPC Name+1` / `trust:NPC Name-1`
- `quest+:Title|description`
- `quest~:id|completed|optional note`

Every turn also applies a small **deterministic tick** (turn counter, time/danger nudge) so state always moves even if the model is vague.

## Original script

[`storyteller_v2.py`](storyteller_v2.py) remains as a CLI reference; the web game logic lives under `backend/app/`.
