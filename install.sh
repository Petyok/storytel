#!/usr/bin/env bash
# One-shot install: Python backend deps + frontend npm packages.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

USE_VENV=1
for arg in "$@"; do
  case "$arg" in
    --system) USE_VENV=0 ;;
    -h|--help)
      echo "Usage: $0 [--system]"
      echo "  default: create/use .venv and pip install backend requirements"
      echo "  --system: pip install with python3 -m pip (no venv)"
      exit 0
      ;;
  esac
done

need() { command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' not found in PATH" >&2; exit 1; }; }

need python3
need npm

echo "==> Backend (Python)"
if [[ "$USE_VENV" -eq 1 ]]; then
  if [[ ! -d "$ROOT/.venv" ]]; then
    python3 -m venv "$ROOT/.venv"
  fi
  # shellcheck source=/dev/null
  PY="$ROOT/.venv/bin/python"
  PIP="$ROOT/.venv/bin/pip"
  [[ -x "$PY" ]] || { echo "error: venv python missing at $PY" >&2; exit 1; }
  "$PY" -m pip install -q --upgrade pip
  "$PIP" install -r "$ROOT/backend/requirements.txt"
  echo "    Using venv: $ROOT/.venv"
else
  python3 -m pip install -r "$ROOT/backend/requirements.txt"
  echo "    Installed with: $(command -v python3)"
fi

echo "==> Frontend (npm)"
(cd "$ROOT/frontend" && npm install)

echo ""
echo "Done."
if [[ "$USE_VENV" -eq 1 ]]; then
  echo "Run API:    cd $ROOT/backend && $ROOT/.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
else
  echo "Run API:    cd $ROOT/backend && python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
fi
echo "Run UI:     cd $ROOT/frontend && npm run dev"
