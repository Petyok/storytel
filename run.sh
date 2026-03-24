#!/usr/bin/env bash
# Start llama-server (if configured), FastAPI (background), Vite (foreground). Ctrl+C stops all.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
RUNRC="$ROOT/.runrc"
export PATH="$ROOT/.local/bin:$PATH"

USE_SYSTEM=0
for arg in "$@"; do
  case "$arg" in
    --system) USE_SYSTEM=1 ;;
    -h|--help)
      echo "Usage: $0 [--system]"
      echo "  Starts local llama-server (if .runrc has LLAMA_MODEL), API on port 8000, UI on 5173."
      echo "  First run asks for the path to your .gguf once and saves it in .runrc (gitignored)."
      echo "  --system  use system python3 instead of .venv"
      echo "  Optional overrides: API_PORT, FRONTEND_PORT, LLAMA_PORT, LLAMA_MODEL"
      exit 0
      ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found in PATH" >&2; exit 1; }; }

need npm

API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LLAMA_PORT="${LLAMA_PORT:-8080}"

# Local overrides (LLAMA_MODEL, STORYTEL_LLAMA_SKIPPED, LLAMA_PORT, …)
load_runrc() {
  [[ -f "$RUNRC" ]] || return 0
  set -a
  # shellcheck disable=SC1090
  source "$RUNRC"
  set +a
}

load_runrc

# One-time (or until edited) model path
ensure_llama_model_config() {
  if [[ -n "${LLAMA_MODEL:-}" ]]; then
    return 0
  fi
  if [[ "${STORYTEL_LLAMA_SKIPPED:-}" == "1" ]]; then
    return 0
  fi

  echo ""
  echo "Local LLM: path to your model file (.gguf). It will be saved in .runrc"
  echo "(Press Enter to skip — you can still run the API/UI and point LLAMA_CPP_URL elsewhere.)"
  read -r -p "GGUF path: " ans || true
  ans="${ans/#\~/$HOME}"
  ans="${ans//[[:space:]]/}"
  if [[ -n "$ans" ]]; then
    if [[ ! -f "$ans" ]]; then
      echo "warning: file not found: $ans (saved anyway — fix path in .runrc if needed)" >&2
    fi
    printf 'LLAMA_MODEL=%q\n' "$ans" >> "$RUNRC"
    export LLAMA_MODEL="$ans"
  else
    printf '%s\n' "STORYTEL_LLAMA_SKIPPED=1" >> "$RUNRC"
    export STORYTEL_LLAMA_SKIPPED=1
  fi
}

resolve_llama_bin() {
  if [[ -x "$ROOT/.local/bin/llama-server" ]]; then
    echo "$ROOT/.local/bin/llama-server"
    return 0
  fi
  if command -v llama-server >/dev/null 2>&1; then
    command -v llama-server
    return 0
  fi
  return 1
}

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

ensure_llama_model_config

if [[ "${STORYTEL_LLAMA_SKIPPED:-}" != "1" ]] && [[ -n "${LLAMA_MODEL:-}" ]]; then
  if LLAMA_BIN="$(resolve_llama_bin)"; then
    mkdir -p "$ROOT/logs"
    LLAMA_LOG="${LLAMA_LOG:-$ROOT/logs/llama-server.log}"
    echo "==> LLM  http://127.0.0.1:${LLAMA_PORT}  ($LLAMA_BIN)"
    echo "    model: $LLAMA_MODEL"
    echo "    log:   $LLAMA_LOG"
    : >"$LLAMA_LOG"
    (
      exec "$LLAMA_BIN" -m "$LLAMA_MODEL" --host 127.0.0.1 --port "$LLAMA_PORT" ${LLAMA_SERVER_EXTRA:-} >>"$LLAMA_LOG" 2>&1
    ) &
    LLAMA_PID=$!
    sleep 0.8
  else
    echo "warning: llama-server not found (.local/bin or PATH). Run: ./install.sh --with-llama" >&2
    echo "         Or install llama.cpp and ensure 'llama-server' is on PATH." >&2
  fi
fi

echo "==> API  http://127.0.0.1:${API_PORT}  (uvicorn)"
(
  cd "$ROOT/backend"
  exec "${PY[@]}" -m uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_PORT}"
) &
BACK_PID=$!

sleep 0.4

echo "==> UI   http://127.0.0.1:${FRONTEND_PORT}  (vite)"
echo "    Press Ctrl+C to stop."
cd "$ROOT/frontend"
npm run dev -- --host 127.0.0.1 --port "${FRONTEND_PORT}"
