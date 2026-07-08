# Fast SQLite database for target vehicles

The tool can read comparison target vehicles from a single local **SQLite**
database (`odriv.sqlite`) instead of the network Access (`.accdb`) shards. This
is much faster: reading and scoring a target vehicle takes well under a second
instead of parsing Access tables over a network drive.

## Using the database

1. Place `odriv.sqlite` in a local folder (e.g. `C:\OdrivDB\`).
2. In the tool, set the shared-database path (HOME page / settings) to that
   folder. When an `odriv.sqlite` is present there, the tool uses it
   automatically; otherwise it falls back to the `.accdb` files.
3. Pick target vehicles as usual — they now read from SQLite.

## Re-converting (when the shared database is updated)

Run the converter, pointing it at the base catalog (which holds the column
layout) and the four data shards:

```
python convert_accdb_to_sqlite.py --catalog _OdrivDB.accdb \
    _OdrivDB_1.accdb _OdrivDB_2.accdb _OdrivDB_3.accdb _OdrivDB_4.accdb \
    odriv.sqlite
```

The `--catalog` file is required: it provides the authoritative column-to-channel
map (the `entete` table) needed to score events correctly. The converter bakes
that map into the SQLite so the database is fully self-contained.

## What's inside

- `projet` — one row per vehicle, keyed by unique `code`
- `event`  — one row per event (vehicle, SDV, channel values as JSON)
- `entete` — the column-to-channel map (col_N → channel name)
- `meta`   — schema version, source files, counts, conversion date

## Saving new projects into SQLite

When the database path points to a folder containing the SQLite file (or an
empty folder where one should live), saving a project ("Save to database" after
calculating the rating) also writes that project — its vehicle row and its
events — into the SQLite database. It then appears in the target-vehicle list
and can be compared against, just like the imported vehicles.

The file can be named anything ending in `.sqlite` (e.g. `odriv.sqlite`); the
tool finds it in the configured folder automatically.
