#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export UNIC_DATA_DIR="${UNIC_DATA_DIR:-$ROOT/data}"
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then npm install; fi
npm run build
cd "$ROOT/backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
. .venv/bin/activate
pip install -q -r requirements.txt
exec uvicorn app.main:app --host 0.0.0.0 --port "${UNIC_PORT:-8000}"
