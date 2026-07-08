"""SQLite bridge — fast reader for the converted ODRIV database (odriv.sqlite).

This mirrors the parts of accdb_bridge the tool uses for comparison targets, but
reads from a single local indexed SQLite file instead of the network .accdb
shards. Produced by convert_accdb_to_sqlite.py.

Schema (see the converter):
  projet : one row per vehicle (original projet columns), PRIMARY KEY (code)
  event  : vehicle_code, vehicle_id, sdv, channels(JSON {"col_N": v, ...})
           INDEX on vehicle_code  -> reading one target vehicle is a single
           indexed query (typically a few ms), then scoring runs unchanged.
  meta   : schema_version, converted_at, source_files, counts

The event channel JSON keeps the EXACT shape the scoring engine expects
(events as {"sdv":..., "col_N":...} dicts), so scoring from SQLite is identical
to scoring from .accdb.
"""
import os
import json
import sqlite3

SQLITE_FILENAME = "odriv.sqlite"


def normalize_path(path):
    """Strip whitespace and surrounding quotes from a configured path."""
    if not path:
        return ""
    return str(path).strip().strip('"').strip("'")


def find_sqlite(path, year=None):
    """Resolve a SQLite database from a configured path that may be the file
    itself or a folder containing one. Returns the absolute file path or None.

    Matching, in order:
      1. the path itself, if it is a .sqlite/.db file
      2. odriv.sqlite (or any *.sqlite) in the folder
      3. if `year` is set: the year subfolder under a parent-style path
      4. the parent folder (when path is already a year subfolder)
    """
    path = normalize_path(path)
    year = str(year).strip() if year else None
    if not path:
        return None
    if os.path.isfile(path) and path.lower().endswith(
            (".sqlite", ".sqlite3", ".db")):
        return os.path.abspath(path)

    def _in_folder(folder):
        if not folder or not os.path.isdir(folder):
            return None
        canonical = os.path.join(folder, SQLITE_FILENAME)
        if os.path.isfile(canonical):
            return os.path.abspath(canonical)
        try:
            matches = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                       if f.lower().endswith((".sqlite", ".sqlite3", ".db"))
                       and os.path.isfile(os.path.join(folder, f))]
        except OSError:
            matches = []
        if matches:
            odriv = [m for m in matches if "odriv" in os.path.basename(m).lower()]
            return os.path.abspath((odriv or matches)[0])
        return None

    folder = path if os.path.isdir(path) else os.path.dirname(path)
    hit = _in_folder(folder)
    if hit:
        return hit
    if year:
        hit = _in_folder(os.path.join(folder, str(year)))
        if hit:
            return hit
    parent = os.path.dirname(folder) if folder else ""
    if parent:
        hit = _in_folder(parent)
        if hit:
            return hit
        if year:
            hit = _in_folder(os.path.join(parent, str(year)))
            if hit:
                return hit
    return None


def db_exists(path, year=None):
    return find_sqlite(path, year) is not None


def _connect(sqlite_path):
    con = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def read_projects(sqlite_path):
    """Return the list of vehicles (projet rows) as dicts, matching the shape
    accdb_bridge.read_projects returns (ID, code, Uniquename, gears, energy,
    Mode, NbGear, software, droopy, priority, aera, Version, target_vehicle...).
    """
    f = find_sqlite(sqlite_path)
    if not f:
        return []
    con = _connect(f)
    try:
        cur = con.execute("SELECT * FROM projet")
        rows = [dict(r) for r in cur.fetchall()]
    finally:
        con.close()
    # normalise: ensure the keys the tool reads exist
    return rows


def read_project_events(sqlite_path, code=None, vehicle_id=None):
    """Return one vehicle's events as channel dicts {"sdv":..., "col_N":...}.

    Match by unique `code` (preferred) or original `vehicle_id`. This is the hot
    path for scoring a comparison target — a single indexed query.
    """
    f = find_sqlite(sqlite_path)
    if not f:
        return []
    con = _connect(f)
    try:
        if code is not None:
            cur = con.execute(
                "SELECT sdv, channels FROM event WHERE vehicle_code=? ORDER BY id",
                (str(code),))
        elif vehicle_id is not None:
            cur = con.execute(
                "SELECT sdv, channels FROM event WHERE vehicle_id=? ORDER BY id",
                (str(vehicle_id),))
        else:
            return []
        events = []
        for r in cur.fetchall():
            ch = json.loads(r["channels"]) if r["channels"] else {}
            ev = {"sdv": r["sdv"]}
            ev.update(ch)
            events.append(ev)
        return events
    finally:
        con.close()


def read_entete_colmap(sqlite_path):
    """Return the authoritative col_N -> channel-name map baked into the SQLite
    (from the base catalog's entete table). Shape mirrors
    accdb_bridge.read_entete_colmap: {col_number: {"table":..., "name":...}}.
    """
    f = find_sqlite(sqlite_path)
    if not f:
        return {}
    con = _connect(f)
    try:
        # entete may be absent in older conversions
        cur = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='entete'")
        if not cur.fetchone():
            return {}
        out = {}
        for r in con.execute(
                "SELECT col_num, table_name, channel_name FROM entete"):
            out[int(r["col_num"])] = {"table": r["table_name"] or "",
                                      "name": (r["channel_name"] or "").strip()}
        return out
    finally:
        con.close()


def _ensure_writable_schema(con):
    """Make sure the projet/event/entete/meta tables exist (for writing into an
    existing DB, or creating a fresh empty one)."""
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS projet (
        "ID" TEXT, "DateCreation" TEXT, "code" TEXT, "droopy" TEXT,
        "gears" TEXT, "energy" TEXT, "priority" TEXT, "milestone" TEXT,
        "aera" TEXT, "target" TEXT, "software" TEXT, "target_vehicle" TEXT,
        "Version" TEXT, "Mode" TEXT, "Uniquename" TEXT, "NbGear" TEXT,
        "ColonneDb" TEXT, PRIMARY KEY ("code"))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS event (
        id INTEGER PRIMARY KEY AUTOINCREMENT, vehicle_code TEXT,
        vehicle_id TEXT, sdv TEXT, channels TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS entete (
        col_num INTEGER PRIMARY KEY, table_name TEXT, channel_name TEXT)""")
    cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_event_vehicle ON event(vehicle_code)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_projet_code ON projet(code)")
    con.commit()


def _header_to_colnum(sqlite_path):
    """Reverse of the entete map: channel-name -> col number, so a new project's
    channel-keyed events can be stored back as col_N JSON."""
    em = read_entete_colmap(sqlite_path)
    out = {}
    for cn, info in em.items():
        nm = (info.get("name") or "").strip()
        if nm and nm not in out:
            out[nm] = cn
    return out


def write_project(sqlite_path, record, events):
    """Insert or update one project (vehicle) and its events in the SQLite DB.

    record : the saved-project record (projet-shaped dict, as built by
             projects_db.project_to_record). Keyed by unique `code`.
    events : list of event dicts {"sdv":..., <channel-name>: value, ...} in the
             tool's internal (channel-name) shape; they are mapped back to col_N
             using the entete so they round-trip with the rest of the database.

    Creates the database/tables if they don't yet exist, so a brand-new SQLite
    can be populated purely from projects created in the tool.
    Returns (code, n_events_written).
    """
    # resolve a concrete file path; if the configured path is a folder with no
    # DB yet, create odriv.sqlite inside it
    f = find_sqlite(sqlite_path)
    if not f:
        folder = sqlite_path if os.path.isdir(sqlite_path) \
            else os.path.dirname(sqlite_path) or "."
        os.makedirs(folder, exist_ok=True)
        f = os.path.join(folder, SQLITE_FILENAME)

    con = sqlite3.connect(f)
    try:
        _ensure_writable_schema(con)
        cur = con.cursor()

        code = str(record.get("code") or "").strip()
        if not code:
            raise ValueError("project has no code")
        uniq = record.get("Uniquename")
        vehicle_id = str(record.get("id") or record.get("ID") or "")

        # ---- upsert the projet row ----
        projet_vals = {
            "ID": vehicle_id, "DateCreation": record.get("DateCreation"),
            "code": code, "droopy": record.get("droopy"),
            "gears": record.get("gears"), "energy": record.get("energy"),
            "priority": record.get("priority"),
            "milestone": str(record.get("milestone") or ""),
            "aera": record.get("aera"), "target": record.get("target"),
            "software": record.get("software"),
            "target_vehicle": record.get("target_vehicle"),
            "Version": record.get("Version"), "Mode": record.get("Mode"),
            "Uniquename": uniq, "NbGear": str(record.get("NbGear") or ""),
            "ColonneDb": record.get("ColonneDb")}
        cols = list(projet_vals.keys())
        # replace by code (the unique key) so re-saving updates in place
        cur.execute("DELETE FROM projet WHERE code=?", (code,))
        cur.execute(
            f'INSERT INTO projet ({",".join(chr(34)+c+chr(34) for c in cols)}) '
            f'VALUES ({",".join("?" * len(cols))})',
            [None if projet_vals[c] is None else str(projet_vals[c])
             for c in cols])

        # ---- replace this vehicle's events ----
        cur.execute("DELETE FROM event WHERE vehicle_code=?", (code,))
        hdr_to_col = _header_to_colnum(f)
        batch = []
        for ev in events:
            sdv = ev.get("sdv")
            channels = {}
            for k, v in ev.items():
                if k == "sdv" or v is None:
                    continue
                if str(k).startswith("col_"):
                    channels[k] = v                       # already col_N
                else:
                    cn = hdr_to_col.get(k)
                    if cn is not None:
                        channels[f"col_{cn}"] = v
            batch.append((code, vehicle_id, sdv,
                          json.dumps(channels, separators=(",", ":"),
                                     default=str)))
        if batch:
            cur.executemany(
                "INSERT INTO event (vehicle_code, vehicle_id, sdv, channels) "
                "VALUES (?,?,?,?)", batch)
        con.commit()
        return code, len(batch)
    finally:
        con.close()


def get_meta(sqlite_path):
    """Return the meta dict (schema_version, converted_at, counts, ...)."""
    f = find_sqlite(sqlite_path)
    if not f:
        return {}
    con = _connect(f)
    try:
        cur = con.execute("SELECT key, value FROM meta")
        return {r["key"]: r["value"] for r in cur.fetchall()}
    finally:
        con.close()
