#!/usr/bin/env python3
"""Print a summary of odriv.sqlite — confirms all shards were merged.

One .sqlite file is correct. It should contain vehicles and events from
_OdrivDB_1.accdb through _OdrivDB_4.accdb (plus the catalog entete map).

Usage:
    python verify_sqlite.py "Y:\\...\\db\\2024\\odriv.sqlite"
    python verify_sqlite.py "Y:\\...\\db\\2024"
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from engine import sqlite_bridge


def main():
    if len(sys.argv) < 2:
        print("usage: verify_sqlite.py <folder-or-odriv.sqlite>")
        sys.exit(1)
    path = sys.argv[1].strip().strip('"')
    sf = sqlite_bridge.find_sqlite(path)
    if not sf:
        print("ERROR: no odriv.sqlite found at", path)
        sys.exit(1)
    meta = sqlite_bridge.get_meta(sf)
    projs = sqlite_bridge.read_projects(sf)
    import sqlite3
    con = sqlite3.connect(f"file:{sf}?mode=ro", uri=True)
    n_events = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    n_linked = con.execute(
        "SELECT COUNT(*) FROM event WHERE vehicle_code IS NOT NULL "
        "AND trim(vehicle_code) != ''").fetchone()[0]
    per_veh = dict(con.execute(
        "SELECT vehicle_code, COUNT(*) FROM event "
        "WHERE vehicle_code IS NOT NULL GROUP BY vehicle_code").fetchall())
    con.close()

    print("=== odriv.sqlite summary ===")
    print("File:      ", sf)
    print("Size:      ", f"{os.path.getsize(sf) / 1e6:.1f} MB")
    print("Converted: ", meta.get("converted_at", "?"))
    print("Sources:   ", meta.get("source_files", "?"))
    print()
    print("Vehicles:  ", len(projs))
    print("Events:    ", f"{n_events:,} total, {n_linked:,} linked to a vehicle")
    if n_events > n_linked:
        print(f"  ({n_events - n_linked:,} orphan events — no vehicle_code match)")
    dup = meta.get("duplicate_codes_skipped")
    if dup and int(dup) > 0:
        print(f"  ({dup} duplicate vehicle row(s) skipped — events still merged)")
    print()
    try:
        per_file = json.loads(meta.get("per_file") or "[]")
    except Exception:
        per_file = []
    if per_file:
        print("Per shard (merged into this one file):")
        for pf in per_file:
            print(f"  {pf.get('file')}: {pf.get('vehicles', 0)} vehicles, "
                  f"{pf.get('events', 0):,} events")
    print()
    zero = [p.get("code") for p in projs
            if p.get("code") and per_veh.get(p.get("code"), 0) == 0]
    if zero:
        print(f"Vehicles with NO events ({len(zero)}) — cannot be used as targets:")
        for c in zero[:15]:
            print(" ", c)
        if len(zero) > 15:
            print(f"  ... and {len(zero) - 15} more")
    else:
        print("All vehicles have at least one event.")
    print()
    print("NOTE: One odriv.sqlite is expected. It replaces all _OdrivDB_*.accdb shards.")


if __name__ == "__main__":
    main()
