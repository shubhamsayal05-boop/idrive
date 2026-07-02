#!/usr/bin/env python3
"""One-shot converter: shared-drive folder layout -> odriv.sqlite

Expected layout (Excel / CFG style):
    <folder>\\_OdrivDB.accdb              <- catalog (entete + projet list)
    <folder>\\<year>\\_OdrivDB_1..4.accdb  <- event shards

Usage:
    python convert_shared_folder_to_sqlite.py "Y:\\Odriv DB\\db" 2024
    python convert_shared_folder_to_sqlite.py "Y:\\Odriv DB\\db"     # all years

Output: odriv.sqlite in the year subfolder (or in <folder> if flat layout).
"""
import os
import sys

# allow running from od-python/ without installing the backend package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from engine import accdb_bridge
from convert_accdb_to_sqlite import convert


def _catalog(files):
    for f in files:
        base = os.path.basename(f)
        if base == "_OdrivDB.accdb":
            return f
    return None


def _shards(files):
    return [f for f in files
            if os.path.basename(f).startswith("_OdrivDB_")]


def main():
    if len(sys.argv) < 2:
        print("usage: convert_shared_folder_to_sqlite.py <folder> [year]")
        print('  e.g. convert_shared_folder_to_sqlite.py "Y:\\Odriv DB\\db" 2024')
        sys.exit(1)

    folder = sys.argv[1].strip().strip('"')
    year = sys.argv[2].strip() if len(sys.argv) > 2 else None

    if not os.path.isdir(folder):
        print("ERROR: folder not found:", folder)
        sys.exit(1)

    files = accdb_bridge.resolve_db_files(folder, year)
    if not files:
        print("ERROR: no _OdrivDB*.accdb files found under", folder)
        if year:
            print("  (looked in", os.path.join(folder, year), "and the folder root)")
        sys.exit(1)

    catalog = _catalog(files)
    shards = _shards(files)
    if not shards:
        print("ERROR: found catalog but no numbered shards (_OdrivDB_1..4.accdb)")
        sys.exit(1)

    # write odriv.sqlite next to the shards
    if year and os.path.isdir(os.path.join(folder, year)):
        out_dir = os.path.join(folder, year)
    elif shards:
        out_dir = os.path.dirname(shards[0])
    else:
        out_dir = folder
    out_path = os.path.join(out_dir, "odriv.sqlite")

    print("Catalog :", os.path.basename(catalog) if catalog else "(none)")
    print("Shards  :", ", ".join(os.path.basename(s) for s in shards))
    print("Output  :", out_path)
    print()

    convert(shards, out_path, catalog_file=catalog)
    print()
    print("Done. In ODRIV, set the shared database path to:")
    print(" ", out_path)
    print("or the folder containing it.")


if __name__ == "__main__":
  main()
