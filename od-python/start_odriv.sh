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
# Rebuild the React UI when sources changed (frontend/build is not in git).
if [ -f frontend/package.json ] && command -v npm >/dev/null; then
  if [ ! -f frontend/build/index.html ] || [ frontend/src/components/modals.jsx -nt frontend/build/index.html ]; then
    echo "Building frontend..."
    (cd frontend && npm install --legacy-peer-deps --silent && npm run build --silent) \
      || echo "Warning: frontend build failed — using existing build if present."
  fi
fi
python run_odriv.py
