# ODRIV — Python Workbench

## One-click run (no MongoDB, no Node required)

**Windows:** double-click `START_ODRIV.bat`
**macOS/Linux:** `./start_odriv.sh`

Requirements: Python 3.11+ on PATH (and internet on the very first run to
install dependencies into a local `.venv`). The launcher then:

1. starts the backend and serves the pre-built frontend on one port,
2. opens your browser at http://127.0.0.1:8001 automatically,
3. uses a real MongoDB if one is reachable at `mongodb://localhost:27017`,
   otherwise runs fully self-contained in memory and persists everything
   to `odriv_data.json` (autosaved every 30 s and on exit, restored on the
   next start).

To stop: Ctrl+C in the console window (your session is saved on exit).

---

# Here are your Instructions
