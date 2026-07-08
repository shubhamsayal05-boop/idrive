#!/usr/bin/env python3
"""Convert the ODRIV shared Access database (.accdb shards) into a single,
indexed SQLite file for fast target-vehicle reads and scoring.

Why SQLite: it is local (no network/VPN round-trips), indexed (jump straight to
one vehicle's rows), and pre-joins the dataSub1/2/3 channel tables once at
conversion time so scoring reads a ready-to-use event list.

Network drives: .accdb files on mapped drives (Y:, etc.) are copied to a local
cache folder first, and the SQLite file is built locally then copied to the
destination. Parsing multi-hundred-column dataSub tables over SMB can take
30+ minutes per table with no visible progress — local copies avoid that.

Output schema (odriv.sqlite):
  projet : one row per vehicle (all projet columns), PRIMARY KEY (code)
  event  : one row per event (vehicle_code, vehicle_id, sdv, channels JSON)
  entete : col_N -> channel name map (from catalog)
  meta   : source files, conversion timestamp, schema version, counts.
"""
import sys
import os
import json
import sqlite3
import time
import datetime
import importlib.util
import subprocess
import shutil

if importlib.util.find_spec("access_parser") is None:
    print("Installing access-parser (one time, needs internet)...", flush=True)
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install",
         "--disable-pip-version-check", "access-parser"])

from access_parser import AccessParser

SCHEMA_VERSION = "sqlite-v1"
DEFAULT_CACHE = os.path.join(os.path.expanduser("~"), ".odriv", "convert_cache")


def _cache_dir():
    d = os.environ.get("ODRIV_CONVERT_CACHE", DEFAULT_CACHE)
    os.makedirs(d, exist_ok=True)
    return d


def _is_probably_network(path):
    """Heuristic: treat non-system local drives as network (mapped shares)."""
    if os.name != "nt":
        return False
    abspath = os.path.abspath(path)
    if abspath.startswith("\\\\"):
        return True
    drive = os.path.splitdrive(abspath)[0].upper()
    return bool(drive) and drive not in ("C:", "D:")


def _local_copy(src, cache_dir=None):
    """Copy a network .accdb to local disk once; reuse if unchanged."""
    cache_dir = cache_dir or _cache_dir()
    base = os.path.basename(src)
    local = os.path.join(cache_dir, base)
    try:
        src_size = os.path.getsize(src)
        src_mtime = os.path.getmtime(src)
    except OSError:
        return src
    if (os.path.isfile(local)
            and os.path.getsize(local) == src_size
            and os.path.getmtime(local) >= src_mtime):
        print(f"    using cached local copy of {base}", flush=True)
        return local
    print(f"    copying {base} ({src_size / 1e6:.0f} MB) to local disk "
          f"(faster than parsing over the network)...", flush=True)
    t0 = time.time()
    tmp = local + ".part"
    shutil.copy2(src, tmp)
    os.replace(tmp, local)
    print(f"    copy finished in {time.time() - t0:.0f}s", flush=True)
    return local


def _stage_paths(accdb_files, out_path, catalog_file, use_local_cache):
    """Return (shard_paths, catalog_path, sqlite_build_path, final_out_path)."""
    final_out = os.path.abspath(out_path)
    cache = _cache_dir()
    build_out = os.path.join(cache, "odriv_build.sqlite")
    if os.path.exists(build_out):
        os.remove(build_out)

    if not use_local_cache:
        return accdb_files, catalog_file, final_out, None

    need_stage = (_is_probably_network(final_out)
                  or any(_is_probably_network(f) for f in accdb_files)
                  or (catalog_file and _is_probably_network(catalog_file)))
    if not need_stage:
        return accdb_files, catalog_file, final_out, None

    print(f"\nLocal staging folder: {cache}", flush=True)
    print("(Re-runs reuse cached copies — delete that folder to force refresh.)\n",
          flush=True)

    shards = [_local_copy(f, cache) for f in accdb_files]
    cat = (_local_copy(catalog_file, cache) if catalog_file else None)
    return shards, cat, build_out, final_out


def _table(db, name, label=None):
    """Parse a table to {col: [values...]} or return None if absent/empty."""
    label = label or name
    print(f"    parsing {label}...", flush=True)
    t0 = time.time()
    try:
        t = db.parse_table(name)
    except Exception as exc:
        print(f"    {label}: failed ({exc})", flush=True)
        return None
    if not t:
        print(f"    {label}: empty", flush=True)
        return None
    cols = list(t.keys())
    if not cols or len(t[cols[0]]) == 0:
        print(f"    {label}: 0 rows", flush=True)
        return None
    n = len(t[cols[0]])
    print(f"    {label}: {n:,} rows in {time.time() - t0:.0f}s", flush=True)
    return t


def convert(accdb_files, out_path, catalog_file=None, use_local_cache=True):
    t0 = time.time()
    shards, catalog, build_path, final_out = _stage_paths(
        accdb_files, out_path, catalog_file, use_local_cache)

    con = sqlite3.connect(build_path)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA temp_store=MEMORY")

    cur.execute("DROP TABLE IF EXISTS projet")
    cur.execute("DROP TABLE IF EXISTS event")
    cur.execute("DROP TABLE IF EXISTS meta")
    cur.execute("DROP TABLE IF EXISTS entete")
    cur.execute(
        "CREATE TABLE entete ("
        "  col_num INTEGER PRIMARY KEY,"
        "  table_name TEXT,"
        "  channel_name TEXT"
        ")")
    n_entete = 0
    if catalog and os.path.isfile(catalog):
        print(f"\n--- reading entete from {os.path.basename(catalog)} ---",
              flush=True)
        cdb = AccessParser(catalog)
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

    projet_cols = None
    cur.execute(
        "CREATE TABLE event ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  vehicle_code TEXT,"
        "  vehicle_id   TEXT,"
        "  sdv          TEXT,"
        "  channels     TEXT"
        ")")
    cur.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    seen_codes = set()
    skipped_dupes = 0
    total_vehicles = 0
    total_events = 0
    per_file = []

    for path in shards:
        fname = os.path.basename(path)
        print(f"\n--- reading {fname} ---", flush=True)
        db = AccessParser(path)

        proj = _table(db, "projet")
        veh_in_file = 0
        id_to_code = {}
        uniq_to_code = {}
        if proj is not None:
            pcols = list(proj.keys())
            if projet_cols is None:
                projet_cols = pcols
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
                    skipped_dupes += 1
                    continue
                seen_codes.add(code)
                vals = [None if row.get(c) is None else str(row.get(c))
                        for c in projet_cols]
                ph = ",".join("?" * len(projet_cols))
                try:
                    cur.execute(f"INSERT INTO projet VALUES ({ph})", vals)
                    veh_in_file += 1
                    total_vehicles += 1
                except sqlite3.IntegrityError:
                    pass

        did = _table(db, "dataId")
        ev_in_file = 0
        if did is not None:
            dcols = list(did.keys())
            n = len(did[dcols[0]])
            uname_col = did.get("UniqueName", [None] * n)
            id_col = did.get("N\u00b0", list(range(1, n + 1)))
            sename_col = did.get(
                "Sous situation de vie, Sub Event Name", [None] * n)

            subs = []
            for tn in ("dataSub1", "dataSub2", "dataSub3"):
                st = _table(db, tn)
                if st is None:
                    continue
                idlist = st.get("idData", [])
                pos = {idd: j for j, idd in enumerate(idlist)}
                chan_cols = [c for c in st.keys() if c.startswith("col_")]
                subs.append((st, pos, chan_cols))
                print(f"      {tn}: {len(chan_cols)} channel columns", flush=True)

            batch = []
            report_every = max(5000, n // 20)
            for i in range(n):
                eid = id_col[i]
                uname = uname_col[i]
                vcode = (id_to_code.get(str(uname))
                         or uniq_to_code.get(str(uname)))
                vid = str(uname) if uname is not None else None
                sdv = sename_col[i]
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
                if (i + 1) % report_every == 0:
                    print(f"      events merged: {i + 1:,} / {n:,}", flush=True)
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
        print(f"    vehicles: {veh_in_file}, events: {ev_in_file:,}",
              flush=True)

    print("\n--- building indexes ---", flush=True)
    cur.execute("CREATE INDEX ix_event_vehicle ON event(vehicle_code)")
    cur.execute("CREATE INDEX ix_event_vehicle_id ON event(vehicle_id)")

    meta = {
        "schema_version": SCHEMA_VERSION,
        "converted_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_files": json.dumps([os.path.basename(f) for f in accdb_files]),
        "catalog_file": os.path.basename(catalog_file) if catalog_file else "",
        "entete_columns": str(n_entete),
        "total_vehicles": str(total_vehicles),
        "total_events": str(total_events),
        "duplicate_codes_skipped": str(skipped_dupes),
        "per_file": json.dumps(per_file),
    }
    for k, v in meta.items():
        cur.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))
    con.commit()
    cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    cur.execute("VACUUM")
    con.commit()
    con.close()

    if final_out:
        os.makedirs(os.path.dirname(final_out) or ".", exist_ok=True)
        print(f"\n--- copying odriv.sqlite to {final_out} ---", flush=True)
        t1 = time.time()
        tmp = final_out + ".part"
        shutil.copy2(build_path, tmp)
        os.replace(tmp, final_out)
        print(f"    copy finished in {time.time() - t1:.0f}s", flush=True)
        result_path = final_out
    else:
        result_path = build_path

    dt = time.time() - t0
    size_mb = os.path.getsize(result_path) / 1e6
    print(f"\n=== DONE in {dt:.0f}s ({dt / 60:.1f} min) ===")
    print(f"  output: {result_path} ({size_mb:.1f} MB)")
    print(f"  vehicles: {total_vehicles}")
    print(f"  events:   {total_events:,}")
    if skipped_dupes:
        print(f"  duplicate codes skipped: {skipped_dupes} "
              f"(events from later shards still merged)")
    return total_vehicles, total_events


if __name__ == "__main__":
    args = sys.argv[1:]
    catalog = None
    if "--catalog" in args:
        ci = args.index("--catalog")
        catalog = args[ci + 1]
        args = args[:ci] + args[ci + 2:]
    if "--no-local-cache" in args:
        args.remove("--no-local-cache")
        use_cache = False
    else:
        use_cache = True
    files = args[:-1]
    out = args[-1]
    if not files:
        print("usage: convert_accdb_to_sqlite.py [--catalog base.accdb] "
              "[--no-local-cache] <db1.accdb> [db2...] <out.sqlite>")
        sys.exit(1)
    convert(files, out, catalog_file=catalog, use_local_cache=use_cache)
