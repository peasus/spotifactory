#!/usr/bin/env bash
set -euo pipefail

# Usage: ./scripts/run_debugpy.sh [host] [port]
# Defaults: host=127.0.0.1 port=5678

HOST=${1:-127.0.0.1}
PORT=${2:-5678}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

VENV="$PROJECT_ROOT/.venv"
if [ -f "$VENV/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
else
  echo "No virtualenv found at $VENV"
  echo "Creating virtualenv and installing dev dependencies (this may take a while)..."
  python -m venv "$VENV"
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
  python -m pip install --upgrade pip
  pip install -e ".[dev]"
fi

echo "Using Python: $(which python)"

python - <<PY
try:
    import debugpy
except Exception:
    import sys, subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "debugpy"]) 
PY

echo "Starting debugpy on ${HOST}:${PORT} and waiting for debugger to attach..."
python -m debugpy --listen ${HOST}:${PORT} --wait-for-client -m spotifactory.main
