#!/usr/bin/env bash
# One-shot install: Python backend deps, frontend npm, optional llama-server binary.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

USE_VENV=1
WITH_LLAMA=0
for arg in "$@"; do
  case "$arg" in
    --system) USE_VENV=0 ;;
    --with-llama) WITH_LLAMA=1 ;;
    -h|--help)
      echo "Usage: $0 [--system] [--with-llama]"
      echo "  default: .venv + pip + npm install"
      echo "  --system: pip without venv"
      echo "  --with-llama: download or build llama-server into .local/bin/"
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

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
else
  PY="python3"
fi

install_llama_server() {
  mkdir -p "$ROOT/.local/bin"
  export PATH="$ROOT/.local/bin:$PATH"

  if [[ -x "$ROOT/.local/bin/llama-server" ]]; then
    echo "==> llama-server already present: $ROOT/.local/bin/llama-server"
    return 0
  fi
  if command -v llama-server >/dev/null 2>&1; then
    echo "==> llama-server already on PATH: $(command -v llama-server)"
    return 0
  fi

  echo "==> llama-server (local inference, OpenAI-compatible /v1/completions)"
  export STORYTEL_LLAMA_DEST="$ROOT/.local/bin"
  if "$PY" "$ROOT/scripts/fetch-llama-server.py"; then
    return 0
  fi

  echo "    Prebuilt zip not available for this platform — building from source…"
  need git
  need cmake
  if command -v g++ >/dev/null 2>&1; then
    : # ok
  elif command -v clang++ >/dev/null 2>&1; then
    export CXX=clang++
  else
    echo "error: need g++ or clang++ to build llama-server" >&2
    return 1
  fi

  SRC="$ROOT/.local/src/llama.cpp"
  rm -rf "$SRC"
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$SRC"
  cmake -S "$SRC" -B "$SRC/build" -DLLAMA_BUILD_SERVER=ON -DCMAKE_BUILD_TYPE=Release
  cmake --build "$SRC/build" --target llama-server -j"$(nproc 2>/dev/null || echo 4)"
  if [[ -x "$SRC/build/bin/llama-server" ]]; then
    cp "$SRC/build/bin/llama-server" "$ROOT/.local/bin/llama-server"
  elif [[ -x "$SRC/build/llama-server" ]]; then
    cp "$SRC/build/llama-server" "$ROOT/.local/bin/llama-server"
  else
    echo "error: build finished but llama-server binary not found under $SRC/build" >&2
    return 1
  fi
  chmod +x "$ROOT/.local/bin/llama-server"
  echo "    Built: $ROOT/.local/bin/llama-server"
}

if [[ "$WITH_LLAMA" -eq 1 ]]; then
  install_llama_server || {
    echo "error: --with-llama failed (see messages above)" >&2
    exit 1
  }
else
  echo ""
  echo "Tip: for a bundled local LLM binary, run:  ./install.sh --with-llama"
fi

echo ""
echo "Done."
echo "Start stack:  ./run.sh"
echo "  (first run will ask where your .gguf model lives and save it in .runrc)"
