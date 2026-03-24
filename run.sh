#!/usr/bin/env bash
# Start FastAPI (background) and Vite dev server (foreground). Ctrl+C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

USE_SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --system) USE_SYSTEM=1 ;;
    -h|--help)
      echo "Usage: $0 [--system]"
      echo "  Starts uvicorn on API_PORT (default 8000) and Vite on FRONTEND_PORT (default 5173)."
      echo "  --system  use python3 instead of .venv/bin/python"
      echo "  Env: API_PORT, FRONTEND_PORT"
      echo "  Optional llama-server: START_LLAMA=1 LLAMA_MODEL=/path/to/model.gguf [LLAMA_PORT=8080] [LLAMA_SERVER_BIN=llama-server] [LLAMA_SERVER_EXTRA='--ctx-size 4096']"
      exit 0
      ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found in PATH" >&2; exit 1; }; }

need npm

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [[ "$USE_SYSTEM" -eq 1 ]]; then
  PY=(python3)
else
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    PY=("$ROOT/.venv/bin/python")
  else
    echo "error: .venv not found. Run ./install.sh first, or use: $0 --system" >&2
    exit 1
  fi
fi

BACK_PID=""
LLAMA_PID=""
cleanup() {
  if [[ -n "${BACK_PID}" ]] && kill -0 "${BACK_PID}" 2>/dev/null; then
    kill -TERM "${BACK_PID}" 2>/dev/null || true
    wait "${BACK_PID}" 2>/dev/null || true
  fi
  if [[ -n "${LLAMA_PID}" ]] && kill -0 "${LLAMA_PID}" 2>/dev/null; then
    kill -TERM "${LLAMA_PID}" 2>/dev/null || true
    wait "${LLAMA_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

LLAMA_PORT="${LLAMA_PORT:-8080}"
if [[ "${START_LLAMA:-0}" == "1" ]]; then
  if [[ -z "${LLAMA_MODEL:-}" ]]; then
    echo "error: START_LLAMA=1 requires LLAMA_MODEL=/path/to/model.gguf" >&2
    exit 1
  fi
  LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-llama-server}"
  need "$LLAMA_SERVER_BIN"
  # shellcheck disable=SC2086
  echo "==> LLM  http://127.0.0.1:${LLAMA_PORT}  ($LLAMA_SERVER_BIN, background)"
  (
    exec "$LLAMA_SERVER_BIN" -m "$LLAMA_MODEL" --host 127.0.0.1 --port "$LLAMA_PORT" $LLAMA_SERVER_EXTRA
  ) &
  LLAMA_PID=$!
  sleep 0.8
fi

echo "==> API  http://127.0.0.1:${API_PORT}  (uvicorn)"
(
  cd "$ROOT/backend"
  exec "${PY[@]}" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_PORT}"
) &
BACK_PID=$!

# Brief pause so the first connection from Vite proxy does not race a cold start
sleep 0.4

echo "==> UI   http://127.0.0.1:${FRONTEND_PORT}  (vite)"
echo "    Press Ctrl+C to stop both."
cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
