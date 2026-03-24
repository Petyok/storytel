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

From the `storytel/` directory:

```bash
chmod +x install.sh
./install.sh
```

This creates `.venv`, installs `backend/requirements.txt`, and runs `npm install` in `frontend/`.

- System Python (no venv): `./install.sh --system`
- **Local LLM binary** (recommended): `./install.sh --with-llama` — tries to download a prebuilt `llama-server` for your OS/arch into `.local/bin/`, or builds from [llama.cpp](https://github.com/ggml-org/llama.cpp) with CMake if no zip matches.

## Run (one script)

After install:

```bash
chmod +x run.sh
./run.sh
```

Starts **`llama-server`** when a model path is configured (see below), **uvicorn** on `8000` (background), and **Vite** on `5173` (foreground). Press **Ctrl+C** to stop.

**First run:** you are asked once for the path to your **`.gguf`** model; it is stored in **`.runrc`** (gitignored). Press Enter to skip local LLM (API/UI still run; set `LLAMA_CPP_URL` if the model runs elsewhere).

Optional `.runrc` variables: `LLAMA_MODEL`, `LLAMA_PORT`, `LLAMA_SERVER_EXTRA` (extra args for `llama-server`), or `STORYTEL_LLAMA_SKIPPED=1` to disable the prompt and local server.

- Use system Python: `./run.sh --system` (requires backend deps on `PATH`).
- Change ports: `API_PORT=9000 FRONTEND_PORT=5174 ./run.sh` — if you change `API_PORT`, update the `proxy` target in `frontend/vite.config.js` to match.

`llama-server` logs go to `logs/llama-server.log` so they do not mix with the Vite terminal.

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
| `LLAMA_CPP_URL` | `http://127.0.0.1:8080` | llama.cpp base URL (no trailing slash) |
| `LLAMA_COMPLETION_PATH` | `/v1/completions` | Route under base URL |
| `LLM_API_STYLE` | `openai_completions` | `openai_completions` (OpenAI-style body, `choices[].text`) or `native` (`/completion`, `n_predict`, `content`) |
| `LLM_OPENAI_MODEL` | `gpt-3.5-turbo-instruct` | `model` field for `/v1/completions` (local server usually ignores the value) |
| `LLM_API_KEY` | *(empty)* | If set, sends `Authorization: Bearer …` |
| `LLM_TIMEOUT_SEC` | `120` | HTTP timeout |
| `MAX_PROMPT_CHARS` | `12000` | Hard cap on assembled prompt |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,...` | Browser origins |
| `LLM_MAX_RETRIES` | `4` | Retries on LLM 5xx / timeout / bad JSON before fallback |
| `LLM_RETRY_BACKOFF_SEC` | `0.6` | Base backoff between retries (seconds) |
| `LLM_GAME_MAX_TOKENS` | `896` | Max completion tokens for story turns (raise if JSON is truncated) |
| `LLM_GAME_TEMPERATURE` | `0.35` | Temperature for story turns (lower helps Qwen/instruct models stick to JSON) |
| `LLM_STOP_SEQUENCES` | `<|im_end|>` | Comma-separated `stop` strings for `/v1/completions` |
| `MADNESS_LIGHT_PER_MAD` | `50` | Story cadence: this many “light” turns, then one “mad” turn |

Endpoints:

- `GET /health` — `{"status":"ok","llm_max_retries":4}` (used by the UI for loading copy)
- `GET /sessions` — list session folder names
- `POST /sessions` — body `{"session_id":"my_save","overwrite":false}` → create (or reset with `overwrite: true`), returns same shape as `GET /session/{id}`; `409` if exists and not overwriting
- `GET /session/{id}` — merged state + last scene + pending choices
- `POST /session/{id}/action` — same as above (JSON response).
- `POST /session/{id}/action/stream` — **NDJSON** stream: lines `{"type":"llm_attempt","current":1,"max":4,"wave":1,"max_waves":3}` during HTTP retries, then `{"type":"result","payload":{...}}` (same shape as the non-stream action response). If the model never returns valid play JSON, the save is **not** advanced and the UI keeps the previous scene/choices (no backup story text).

## llama.cpp (HTTP)

Example (adjust model path and port):

```bash
./llama-server -m /path/to/model.gguf -c 4096 --host 127.0.0.1 --port 8080
```

If your server runs elsewhere:

```bash
export LLAMA_CPP_URL=http://127.0.0.1:YOUR_PORT
```

By default the backend uses **OpenAI-compatible** `POST /v1/completions` (see [llama.cpp server docs](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)): body includes `prompt`, `max_tokens`, `temperature`, `top_p`, `repeat_penalty`, and `model`. The completion text is read from `choices[0].text`. For older servers that only expose the non-OAI route, set `LLM_API_STYLE=native` and `LLAMA_COMPLETION_PATH=/completion`.

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
