#!/usr/bin/env bash
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Python 3.11+ required."; exit 1; }
[ -d .venv ] || { echo "Creating environment..."; python3 -m venv .venv; }
. .venv/bin/activate
if [ ! -f .venv/deps_ok ]; then
  echo "Installing dependencies (one time)..."
  pip install --upgrade pip --quiet
  pip install -r backend/requirements.txt || { echo "Install failed - check internet and retry."; exit 1; }
  touch .venv/deps_ok
fi
python run_odriv.py
