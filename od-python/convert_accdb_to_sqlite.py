#!/usr/bin/env python3
"""Convert the ODRIV shared Access database (.accdb shards) into a single,
indexed SQLite file for fast target-vehicle reads and scoring.

Why SQLite: it is local (no network/VPN round-trips), indexed (jump straight to
one vehicle's rows), and pre-joins the dataSub1/2/3 channel tables once at
conversion time so scoring reads a ready-to-use event list.

Output schema (odriv.sqlite):
  projet : one row per vehicle (all projet columns), PRIMARY KEY (code)
           + a unique row even when ID is duplicated/null across shards.
  event  : one row per event:
             vehicle_code TEXT   -> projet.code
             vehicle_id   TEXT   -> original projet.ID (for reference)
             sdv          TEXT   -> sub-event / SDV name
             channels     TEXT   -> JSON {"col_1": v, "col_2": v, ...}
           INDEX on vehicle_code (the hot path for "score this target").
  meta   : source files, conversion timestamp, schema version, counts.

The channels JSON keeps the EXACT shape the scoring engine already expects
(events as {"sdv":..., "col_N":...} dicts), so scoring from SQLite is identical
to scoring from .accdb — no engine changes required.
"""
import sys
import os
import json
import sqlite3
import time
import datetime
import importlib.util
import subprocess

if importlib.util.find_spec("access_parser") is None:
    print("Installing access-parser (one time, needs internet)...", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install",
         "--disable-pip-version-check", "access-parser"])

from access_parser import AccessParser

SCHEMA_VERSION = "sqlite-v1"


def _table(db, name):
    """Parse a table to {col: [values...]} or return None if absent/empty."""
    try:
        t = db.parse_table(name)
    except Exception:
        return None
    if not t:
        return None
    cols = list(t.keys())
    if not cols or len(t[cols[0]]) == 0:
        return None
    return t


def convert(accdb_files, out_path, catalog_file=None):
    t0 = time.time()
    con = sqlite3.connect(out_path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")

    # ---- schema ----
    cur.execute("DROP TABLE IF EXISTS projet")
    cur.execute("DROP TABLE IF EXISTS event")
    cur.execute("DROP TABLE IF EXISTS meta")
    cur.execute("DROP TABLE IF EXISTS entete")
    # entete: the authoritative col_N -> channel-name map (from the base
    # catalog). Without it, events cannot be scored. Stored once here so the
    # SQLite database is self-contained.
    cur.execute(
        "CREATE TABLE entete ("
        "  col_num INTEGER PRIMARY KEY,"
        "  table_name TEXT,"
        "  channel_name TEXT"
        ")")
    n_entete = 0
    if catalog_file and os.path.isfile(catalog_file):
        print(f"\n--- reading entete from {os.path.basename(catalog_file)} ---",
              flush=True)
        cdb = AccessParser(catalog_file)
        et = _table(cdb, "entete")
        if et is not None:
            ncol = len(et.get("IdCol", []))
            rows_e = []
            for i in range(ncol):
                idc = str(et["IdCol"][i])
                try:
                    cn = int(idc.replace("col_", ""))
                except ValueError:
                    continue
                tbl = str(et.get("TableCol", [""] * ncol)[i])
                nm = str(et.get("DescriptionCol", [""] * ncol)[i]).strip()
                rows_e.append((cn, tbl, nm))
            cur.executemany(
                "INSERT OR REPLACE INTO entete VALUES (?,?,?)", rows_e)
            n_entete = len(rows_e)
            print(f"    entete columns: {n_entete}", flush=True)
        con.commit()

    # projet columns are discovered from the first shard that has the table
    projet_cols = None
    cur.execute(
        "CREATE TABLE event ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  vehicle_code TEXT,"
        "  vehicle_id   TEXT,"
        "  sdv          TEXT,"
        "  channels     TEXT"      # JSON
        ")")
    cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    seen_codes = set()        # de-dup vehicles by unique code
    total_vehicles = 0
    total_events = 0
    per_file = []

    for path in accdb_files:
        fname = os.path.basename(path)
        print(f"\n--- reading {fname} ---", flush=True)
        db = AccessParser(path)

        # ===== vehicles (projet) =====
        proj = _table(db, "projet")
        veh_in_file = 0
        # map this shard's project ID -> code, for linking events below
        id_to_code = {}
        uniq_to_code = {}
        if proj is not None:
            pcols = list(proj.keys())
            if projet_cols is None:
                projet_cols = pcols
                # build the projet table now that we know its columns
                coldefs = ", ".join(f'"{c}" TEXT' for c in projet_cols)
                cur.execute(
                    f'CREATE TABLE projet ({coldefs}, '
                    f'PRIMARY KEY ("code"))')
                cur.execute('CREATE INDEX ix_projet_id ON projet("ID")')
            n = len(proj[pcols[0]])
            for i in range(n):
                row = {c: proj[c][i] for c in pcols}
                code = row.get("code")
                if code is None or str(code).strip() == "":
                    continue
                code = str(code)
                pid = str(row.get("ID")) if row.get("ID") is not None else None
                uniq = row.get("Uniquename")
                id_to_code.setdefault(pid, code)
                if uniq is not None:
                    uniq_to_code.setdefault(str(uniq), code)
                if code in seen_codes:
                    continue          # vehicle already taken from another shard
                seen_codes.add(code)
                vals = [None if row.get(c) is None else str(row.get(c))
                        for c in projet_cols]
                ph = ",".join("?" * len(projet_cols))
                try:
                    cur.execute(f"INSERT INTO projet VALUES ({ph})", vals)
                    veh_in_file += 1
                    total_vehicles += 1
                except sqlite3.IntegrityError:
                    pass              # duplicate code key, keep first

        # ===== events (dataId + dataSub1/2/3) =====
        did = _table(db, "dataId")
        ev_in_file = 0
        if did is not None:
            dcols = list(did.keys())
            n = len(did[dcols[0]])
            uname_col = did.get("UniqueName", [None] * n)
            id_col = did.get("N\u00b0", list(range(1, n + 1)))
            sename_col = did.get(
                "Sous situation de vie, Sub Event Name", [None] * n)
            code_col = did.get("code", [None] * n)   # acquisition code (not vehicle)

            # build idData -> row-position maps for each dataSub table once
            subs = []
            for tn in ("dataSub1", "dataSub2", "dataSub3"):
                st = _table(db, tn)
                if st is None:
                    continue
                idlist = st.get("idData", [])
                pos = {idd: j for j, idd in enumerate(idlist)}
                chan_cols = [c for c in st.keys() if c.startswith("col_")]
                subs.append((st, pos, chan_cols))

            batch = []
            for i in range(n):
                eid = id_col[i]
                # resolve vehicle code from the event's UniqueName (the projet ID
                # or uniquename); fall back to the raw value as a last resort
                uname = uname_col[i]
                vcode = (id_to_code.get(str(uname))
                         or uniq_to_code.get(str(uname)))
                vid = str(uname) if uname is not None else None
                sdv = sename_col[i]
                # assemble channel dict from the dataSub tables
                channels = {}
                for st, pos, chan_cols in subs:
                    j = pos.get(eid)
                    if j is None:
                        continue
                    for c in chan_cols:
                        v = st[c][j]
                        if v is not None and v != "":
                            channels[c] = v
                batch.append((vcode, vid, sdv, json.dumps(channels,
                              separators=(",", ":"), default=str)))
                if len(batch) >= 5000:
                    cur.executemany(
                        "INSERT INTO event "
                        "(vehicle_code, vehicle_id, sdv, channels) "
                        "VALUES (?,?,?,?)", batch)
                    ev_in_file += len(batch)
                    batch = []
            if batch:
                cur.executemany(
                    "INSERT INTO event "
                    "(vehicle_code, vehicle_id, sdv, channels) "
                    "VALUES (?,?,?,?)", batch)
                ev_in_file += len(batch)
            total_events += ev_in_file

        con.commit()
        per_file.append({"file": fname, "vehicles": veh_in_file,
                         "events": ev_in_file})
        print(f"    vehicles: {veh_in_file}, events: {ev_in_file}", flush=True)

    # ---- index the hot path ----
    print("\n--- building indexes ---", flush=True)
    cur.execute("CREATE INDEX ix_event_vehicle ON event(vehicle_code)")
    cur.execute("CREATE INDEX ix_event_vehicle_id ON event(vehicle_id)")

    # ---- meta ----
    meta = {
        "schema_version": SCHEMA_VERSION,
        "converted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_files": json.dumps([os.path.basename(f) for f in accdb_files]),
        "catalog_file": os.path.basename(catalog_file) if catalog_file else "",
        "entete_columns": str(n_entete),
        "total_vehicles": str(total_vehicles),
        "total_events": str(total_events),
        "per_file": json.dumps(per_file),
    }
    for k, v in meta.items():
        cur.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))
    con.commit()
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    cur.execute("VACUUM")
    con.commit()
    con.close()

    dt = time.time() - t0
    size_mb = os.path.getsize(out_path) / 1e6
    print(f"\n=== DONE in {dt:.1f}s ===")
    print(f"  output: {out_path} ({size_mb:.1f} MB)")
    print(f"  vehicles: {total_vehicles}")
    print(f"  events:   {total_events}")
    return total_vehicles, total_events


if __name__ == "__main__":
    args = sys.argv[1:]
    # optional: --catalog <base _OdrivDB.accdb> holds the entete map
    catalog = None
    if "--catalog" in args:
        ci = args.index("--catalog")
        catalog = args[ci + 1]
        args = args[:ci] + args[ci + 2:]
    files = args[:-1]
    out = args[-1]
    if not files:
        print("usage: convert_accdb_to_sqlite.py [--catalog base.accdb] "
              "<db1.accdb> [db2...] <out.sqlite>")
        sys.exit(1)
    convert(files, out, catalog_file=catalog)
