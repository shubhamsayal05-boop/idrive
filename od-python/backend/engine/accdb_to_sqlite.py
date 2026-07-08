"""Convert the shared Access database (_OdrivDB_*.accdb shards) into a single
indexed SQLite file optimised for fast target-vehicle reads.

Why SQLite: the tool no longer needs Access/Excel compatibility, and a local
indexed SQLite removes three sources of slowness in the old path —
  (1) network-drive round-trips (the file is now local),
  (2) full-table scans (vehicle lookups are indexed on `code`), and
  (3) per-event reassembly across dataSub1/2/3 (channels are pre-merged once,
      at conversion time, into a single ready-to-use row per event).

Output schema (odriv.sqlite):
  projet(<all original projet columns>, _db_file)   UNIQUE INDEX on code
  events(id, vehicle_code, project_id, sdv, channels_json)
        INDEX on vehicle_code
  meta(key, value)   -- provenance: source files, dates, schema version, counts

Usage:
    python -m engine.accdb_to_sqlite <out.sqlite> <shard1.accdb> [shard2 ...]
or import and call convert().
"""
from __future__ import annotations
import os
import sys
import json
import time
import sqlite3

SCHEMA_VERSION = "1"


def _open_access(path):
    from access_parser import AccessParser
    return AccessParser(path)


def _table(db, name):
    """Return (columns, rowcount, getter(col,i)) for an Access table, or None."""
    try:
        t = db.parse_table(name)
    except Exception:
        return None
    cols = list(t.keys())
    if not cols:
        return [], 0, t
    n = len(t[cols[0]])
    return cols, n, t


def convert(out_path, accdb_paths, progress=None):
    """Convert one or more .accdb shards into a single SQLite file.

    progress: optional callable(str) for status messages.
    Returns a dict summary {projects, events, vehicles, seconds, out_path}.
    """
    def log(msg):
        if progress:
            progress(msg)

    t_start = time.time()
    if os.path.exists(out_path):
        os.remove(out_path)

    con = sqlite3.connect(out_path)
    cur = con.cursor()
    # Pragmas for fast bulk insert (durability relaxed only during build).
    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA temp_store=MEMORY")

    # ---- discover the projet schema from the first shard that has one ----
    projet_cols = None
    for p in accdb_paths:
        db = _open_access(p)
        info = _table(db, "projet")
        if info and info[0]:
            projet_cols = info[0]
            break
    if not projet_cols:
        raise RuntimeError("No 'projet' table found in any shard.")

    # Build projet table DDL (all original columns as TEXT, + _db_file).
    safe_cols = [c for c in projet_cols]
    col_ddl = ", ".join(f'"{c}" TEXT' for c in safe_cols)
    cur.execute(f'CREATE TABLE projet ({col_ddl}, "_db_file" TEXT)')

    cur.execute(
        "CREATE TABLE events ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  vehicle_code TEXT,"
        "  project_id TEXT,"
        "  sdv TEXT,"
        "  channels_json TEXT)")

    cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    total_projects = 0
    total_events = 0
    seen_codes = set()
    all_projets = []
    id_to_code = {}

    for p in accdb_paths:
        fname = os.path.basename(p)
        log(f"Reading {fname} …")
        db = _open_access(p)

        # ---- projet rows ----
        pinfo = _table(db, "projet")
        if pinfo and pinfo[1]:
            pcols, pn, pt = pinfo
            for i in range(pn):
                row = [(_s(pt[c][i]) if c in pt else None) for c in projet_cols]
                row.append(fname)
                pid = _s(pt["ID"][i]) if "ID" in pt else None
                code = _s(pt["code"][i]) if "code" in pt else None
                all_projets.append((row, fname, pid, code))
                if pid is not None and code is not None:
                    id_to_code[pid] = code
            total_projects += pn
            log(f"  {pn} projects")

        # ---- build event channel map: idData -> {col_name: value} ----
        # dataId: N° -> (UniqueName=project_id, code=vehicle, sdv)
        dinfo = _table(db, "dataId")
        if not dinfo or not dinfo[1]:
            log("  (no events)")
            continue
        dcols, dn, dt = dinfo
        # locate the sdv column (name varies slightly)
        sdv_col = next((c for c in dcols if "Sub Event Name" in c
                        or "situation de vie" in c.lower()), None)

        # Merge dataSub1/2/3 channel values keyed by idData.
        # Each dataSub row: idData -> {col_k: value} for non-null channel cols.
        chan_by_iddata = {}
        for sub in ("dataSub1", "dataSub2", "dataSub3"):
            sinfo = _table(db, sub)
            if not sinfo or not sinfo[1]:
                continue
            scols, sn, st = sinfo
            # channel columns are the col_* ones (skip N°, idData)
            chan_cols = [c for c in scols if c.startswith("col_")]
            id_arr = st["idData"]
            for i in range(sn):
                idd = id_arr[i]
                d = chan_by_iddata.get(idd)
                if d is None:
                    d = {}
                    chan_by_iddata[idd] = d
                for c in chan_cols:
                    v = st[c][i]
                    if v is not None and v != "":
                        d[c] = _s(v)
            log(f"  merged {sub} ({sn} rows)")

        # Emit one events row per dataId entry, attaching its channel map.
        n_arr = dt["N°"]
        uniq_arr = dt["UniqueName"] if "UniqueName" in dt else None
        sdv_arr = dt[sdv_col] if sdv_col else None
        batch = []
        for i in range(dn):
            num = n_arr[i]
            chans = chan_by_iddata.get(num, {})
            pid = _s(uniq_arr[i]) if uniq_arr else None
            batch.append((
                id_to_code.get(pid),
                pid,
                _s(sdv_arr[i]) if sdv_arr else None,
                json.dumps(chans, ensure_ascii=False, separators=(",", ":")),
            ))
            if len(batch) >= 5000:
                cur.executemany(
                    "INSERT INTO events (vehicle_code, project_id, sdv, "
                    "channels_json) VALUES (?,?,?,?)", batch)
                batch = []
        if batch:
            cur.executemany(
                "INSERT INTO events (vehicle_code, project_id, sdv, "
                "channels_json) VALUES (?,?,?,?)", batch)
        total_events += dn
        log(f"  {dn} events")
        con.commit()

    # ---- resolve duplicate codes: keep the project_id with most events ----
    log("Resolving duplicate vehicle codes ...")
    cur.execute("SELECT project_id, COUNT(*) FROM events GROUP BY project_id")
    ev_per_pid = {pid: c for pid, c in cur.fetchall()}
    by_code = {}
    for row, fname, pid, code in all_projets:
        by_code.setdefault(code, []).append((row, pid))
    keep_rows = []
    dropped = 0
    for code, entries in by_code.items():
        if len(entries) == 1:
            keep_rows.append(entries[0][0])
        else:
            best = max(entries, key=lambda e: ev_per_pid.get(e[1], 0))
            keep_rows.append(best[0])
            dropped += len(entries) - 1
            for dpid in [e[1] for e in entries if e[1] != best[1]]:
                cur.execute("DELETE FROM events WHERE project_id=?", (dpid,))
        if code is not None:
            seen_codes.add(code)
    if dropped:
        log(f"  merged {dropped} duplicate vehicle(s) (kept the richest copy)")
    ph = ",".join(["?"] * (len(projet_cols) + 1))
    cur.executemany(f"INSERT INTO projet VALUES ({ph})", keep_rows)
    con.commit()

    # ---- indexes (built after bulk insert for speed) ----
    log("Building indexes ...")
    cur.execute("CREATE UNIQUE INDEX ix_projet_code ON projet(code)")
    cur.execute("CREATE INDEX ix_projet_id ON projet(ID)")
    cur.execute("CREATE INDEX ix_events_vehicle ON events(vehicle_code)")
    cur.execute("CREATE INDEX ix_events_project ON events(project_id)")

    # ---- meta / provenance ----
    elapsed = round(time.time() - t_start, 1)
    meta = {
        "schema_version": SCHEMA_VERSION,
        "source_files": json.dumps([os.path.basename(p) for p in accdb_paths]),
        "converted_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "projects": str(total_projects),
        "events": str(total_events),
        "vehicles": str(len(seen_codes)),
    }
    cur.executemany("INSERT INTO meta VALUES (?,?)", list(meta.items()))

    con.commit()
    # Restore safe durability + compact.
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    log("Optimising …")
    cur.execute("VACUUM")
    cur.execute("ANALYZE")
    con.commit()
    con.close()

    return {"projects": total_projects, "events": total_events,
            "vehicles": len(seen_codes), "seconds": elapsed,
            "out_path": out_path}


def _s(v):
    """Coerce an Access cell to a clean string (or None)."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return str(v)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python -m engine.accdb_to_sqlite <out.sqlite> "
              "<shard1.accdb> [shard2.accdb ...]")
        sys.exit(1)
    out = sys.argv[1]
    shards = sys.argv[2:]
    summary = convert(out, shards, progress=lambda m: print("  " + m))
    print("\nDone:", summary)
