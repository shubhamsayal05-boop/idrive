"""ODRIV one-click launcher.

Run:  python run_odriv.py        (or double-click START_ODRIV.bat / start_odriv.sh)

Behavior:
- If a real MongoDB is reachable at MONGO_URL (default localhost:27017),
  it is used and data persists there.
- Otherwise an in-memory Mongo (mongomock) is used transparently, and all
  collections are snapshotted to ./odriv_data.json (restored on next start,
  autosaved every 30 s and on shutdown). Zero external services required.
- Serves API + the built frontend on one port and opens the browser.
"""
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

# ----------------------------------------------------------- self-healing deps
# If a previous install was interrupted (or the venv is fresh), install the
# missing runtime packages automatically before anything else is imported.
_REQUIRED = {
    "fastapi": "fastapi", "uvicorn": "uvicorn", "motor": "motor",
    "pymongo": "pymongo", "mongomock_motor": "mongomock-motor",
    "dotenv": "python-dotenv", "multipart": "python-multipart",
    "openpyxl": "openpyxl", "pptx": "python-pptx", "docx": "python-docx",
    "reportlab": "reportlab", "matplotlib": "matplotlib",
    "access_parser": "access-parser", "jaydebeapi": "jaydebeapi",
    "jpype": "JPype1",
}
_missing = [pkg for mod, pkg in _REQUIRED.items()
            if importlib.util.find_spec(mod) is None]
if _missing:
    print(f"[ODRIV] Installing missing packages (one time): {', '.join(_missing)}")
    subprocess.check_call([sys.executable, "-m", "pip", "install",
                           "--disable-pip-version-check", *_missing])
    print("[ODRIV] Dependencies ready.")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "backend"))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "odriv")

HOST, PORT = "127.0.0.1", 8001
URL = f"http://{HOST}:{PORT}"
STORE = os.path.join(HERE, "odriv_data.json")


def mongo_alive(url: str, timeout_s: float = 1.5) -> bool:
    try:
        from pymongo import MongoClient
        MongoClient(url, serverSelectionTimeoutMS=int(timeout_s * 1000)) \
            .admin.command("ping")
        return True
    except Exception:
        return False


USE_MOCK = not mongo_alive(os.environ["MONGO_URL"])
if USE_MOCK:
    import mongomock_motor
    import motor.motor_asyncio
    motor.motor_asyncio.AsyncIOMotorClient = mongomock_motor.AsyncMongoMockClient
    print("[ODRIV] No MongoDB detected -> in-memory mode "
          f"(persisted to {os.path.basename(STORE)})")
else:
    print(f"[ODRIV] Using MongoDB at {os.environ['MONGO_URL']}")

import uvicorn          # noqa: E402
import server           # noqa: E402  (registers its own startup/shutdown)

if USE_MOCK:
    async def _dump():
        out = {}
        for coll in await server.db.list_collection_names():
            docs = await server.db[coll].find({}, {"_id": 0}).to_list(200000)
            out[coll] = docs
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, default=str)
        os.replace(tmp, STORE)

    @server.app.on_event("startup")
    async def _restore_and_autosave():
        if os.path.exists(STORE):
            try:
                with open(STORE, encoding="utf-8") as f:
                    data = json.load(f)
                for coll, docs in data.items():
                    await server.db[coll].delete_many({})
                    if docs:
                        await server.db[coll].insert_many(docs)
                print(f"[ODRIV] Restored previous session "
                      f"({sum(len(d) for d in data.values())} records)")
            except Exception as exc:           # corrupt snapshot must not block boot
                print(f"[ODRIV] Snapshot restore skipped: {exc}")

        async def autosave():
            while True:
                await asyncio.sleep(30)
                try:
                    await _dump()
                except Exception:
                    pass
        asyncio.get_event_loop().create_task(autosave())

    @server.app.on_event("shutdown")
    async def _save_on_exit():
        try:
            await _dump()
            print("[ODRIV] Session saved.")
        except Exception as exc:
            print(f"[ODRIV] Save on exit failed: {exc}")


def _open_browser_when_ready():
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{URL}/api/state", timeout=1)
            webbrowser.open(URL)
            print(f"[ODRIV] Running at {URL}  (Ctrl+C to stop)")
            return
        except Exception:
            time.sleep(0.5)


def _port_in_use(host, port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _is_our_server():
    try:
        urllib.request.urlopen(f"{URL}/api/state", timeout=1.5)
        return True
    except Exception:
        return False


def _pause(msg):
    """input() that won't crash when there's no console (launched by a script,
    double-clicked in some shells, or run head-less). Falls back to a short
    sleep so the message is still visible briefly."""
    try:
        if sys.stdin and sys.stdin.isatty():
            input(msg)
        else:
            print(msg)
            time.sleep(2)
    except (EOFError, OSError):
        print(msg)
        time.sleep(2)


def _free_stale_port():
    """If 8001 is held by a previous ODRIV instance, reuse or clear it."""
    # Test/CI escape hatch: skip the interactive 'already running' handling.
    if os.environ.get("ODRIV_NO_PORT_GUARD") == "1":
        if _port_in_use(HOST, PORT):
            try:
                if os.name == "nt":
                    out = subprocess.check_output(
                        f'netstat -ano -p tcp | findstr :{PORT}', shell=True, text=True)
                    pids = {line.split()[-1] for line in out.splitlines()
                            if f":{PORT}" in line and line.split()[-1].isdigit()}
                    for pid in pids:
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True,
                                       capture_output=True)
                else:
                    subprocess.run(["fuser", "-k", f"{PORT}/tcp"],
                                   capture_output=True)
                time.sleep(1.5)
            except Exception:
                pass
        return not _port_in_use(HOST, PORT)
    if not _port_in_use(HOST, PORT):
        return True
    if _is_our_server():
        print("[ODRIV] Already running -> opening that window in your browser.")
        webbrowser.open(URL)
        _pause("\nPress Enter to close this window (the other one keeps running)...")
        sys.exit(0)
    # held by a dead/zombie process -> try to free it
    print("[ODRIV] Port 8001 busy from a previous run -> clearing it...")
    try:
        if os.name == "nt":
            out = subprocess.check_output(
                f'netstat -ano -p tcp | findstr :{PORT}', shell=True, text=True)
            pids = {line.split()[-1] for line in out.splitlines()
                    if f":{PORT}" in line and line.split()[-1].isdigit()}
            for pid in pids:
                subprocess.run(f"taskkill /F /PID {pid}", shell=True,
                               capture_output=True)
        else:
            subprocess.run(["fuser", "-k", f"{PORT}/tcp"], capture_output=True)
        time.sleep(1.5)
    except Exception as exc:
        print(f"[ODRIV] Could not auto-clear the port ({exc}). "
              f"Close any other ODRIV window, or open {URL} directly.")
        _pause("Press Enter to exit...")
        sys.exit(1)
    return not _port_in_use(HOST, PORT)


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    _free_stale_port()
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(server.app, host=HOST, port=PORT, log_level="warning")
