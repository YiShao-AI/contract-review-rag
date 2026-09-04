#!/usr/bin/env bash
# One-command start (Linux/macOS): creates the venv and .env on first run.
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8090}"

if [ ! -d .venv ]; then
  echo "First run — creating virtualenv and installing dependencies…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env with the fully local Ollama configuration."
fi

echo "Starting on http://localhost:${PORT}"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
