@echo off
rem One-command start (Windows): creates the venv and .env on first run.
cd /d "%~dp0"

if "%PORT%"=="" set PORT=8090

if not exist .venv (
  echo First run - creating virtualenv and installing dependencies...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\pip install --quiet -r requirements.txt
)

if not exist .env (
  copy .env.example .env >nul
  echo Created .env with the fully local Ollama configuration.
)

echo Starting on http://localhost:%PORT%
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port %PORT%
