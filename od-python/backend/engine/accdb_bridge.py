"""Shared Access database bridge — read AND write the shared _OdrivDB_*.accdb.

Read  : pure-Python via `access-parser` (works on any platform, no Java).
Write : via UCanAccess (a pure-Java JDBC driver) through JayDeBeApi. UCanAccess
        runs on Windows/Mac/Linux and writes real .accdb files without needing
        Microsoft Access installed. The required jars are fetched automatically
        on first write (cached under ~/.odriv/ucanaccess) so the user does not
        have to install anything manually — they only need a Java runtime, which
        the launcher checks for.

This lets the tool use the shared database file directly: open it
to import existing saved projects, and save new processed projects back into it
in the exact `projet` / `dataId` / `dataSub1..3` schema.

Schema (reverse-engineered from _OdrivDB_1.accdb):
  projet     : ID, DateCreation, code, droopy, gears, energy, priority,
               milestone, aera, target, software, target_vehicle, Version, Mode,
               Uniquename, NbGear, ColonneDb
  dataId     : N°, UniqueName(=projet.ID), code, "Sous situation de vie, Sub Event Name"
  dataSub1   : N°, idData(=dataId.N°), col_1 .. col_255
  dataSub2   : N°, idData, col_256 .. col_500
  dataSub3   : N°, idData, col_501 .. col_742
"""
from __future__ import annotations
import os
import glob
import urllib.request


# ---------------------------------------------------- folder / multi-DB support
# The shared configuration stores a FOLDER (e.g. Y:\...\Odriv DB\db), not a file.
# Inside it the databases are _OdrivDB_1.accdb .. _OdrivDB_4.accdb (4 shards used
# as a load balancer). A path may therefore be a folder OR a direct .accdb file.

def resolve_db_files(path, year=None):
    """Return the list of .accdb files for a configured path, matching the shared
    real layout:

        <folder>\\_OdrivDB.accdb              <- catalog (projet list)
        <folder>\\<year>\\_OdrivDB_1..4.accdb  <- event shards (per year)

    So we collect the base catalog AND the numbered shards inside the year
    subfolder(s). `year` (e.g. "2024", from CFG B3) selects which year folder;
    if None, every year subfolder that contains _OdrivDB_* shards is included.

    - If `path` is a direct .accdb file: return just that file.
    - If `path` is a folder: return the catalog + numbered shards (recursing one
      level into year subfolders).
    Ordered with the catalog first, then shards by their _OdrivDB_<N> index.
    """
    if not path:
        return []
    p = path.strip().strip('"')
    if os.path.isfile(p) and p.lower().endswith(".accdb"):
        return [p]
    if not os.path.isdir(p):
        return []

    def _idx(f):
        base = os.path.basename(f)
        num = "".join(ch for ch in base.replace(".accdb", "") if ch.isdigit())
        return int(num) if num else 0

    found = []
    # 1) the base catalog directly in the folder (_OdrivDB.accdb, no number)
    for f in glob.glob(os.path.join(p, "_OdrivDB.accdb")):
        found.append(f)
    # 2) any numbered shards directly in the folder (flat layout)
    flat_shards = [f for f in glob.glob(os.path.join(p, "_OdrivDB_*.accdb"))]
    # 3) numbered shards inside year subfolders (the real layout)
    year_dirs = []
    if year:
        yd = os.path.join(p, str(year))
        if os.path.isdir(yd):
            year_dirs.append(yd)
    else:
        for d in sorted(glob.glob(os.path.join(p, "*"))):
            if os.path.isdir(d) and glob.glob(os.path.join(d, "_OdrivDB_*.accdb")):
                year_dirs.append(d)
    sub_shards = []
    for yd in year_dirs:
        sub_shards.extend(glob.glob(os.path.join(yd, "_OdrivDB_*.accdb")))

    shards = sorted(set(flat_shards + sub_shards), key=_idx)
    # if nothing matched the _OdrivDB naming at all, fall back to any *.accdb here
    if not found and not shards:
        anyf = glob.glob(os.path.join(p, "*.accdb"))
        return sorted(anyf, key=_idx)
    return found + shards


def read_entete_colmap(accdb_path, year=None):
    """Read the `entete` table from the catalog: the authoritative
    col_N -> (table, channel-name) dictionary used to lay out the
    dataSub columns. Returns {col_number: {"table":..., "name":...}}.
    Looks in the base catalog (_OdrivDB.accdb) where `entete` lives."""
    from access_parser import AccessParser
    out = {}
    for f in resolve_db_files(accdb_path, year):
        try:
            db = AccessParser(f)
            if "entete" not in db.catalog:
                continue
            t = db.parse_table("entete")
            n = len(t["IdCol"]) if "IdCol" in t else 0
            for i in range(n):
                idcol = str(t["IdCol"][i])
                try:
                    cn = int(idcol.replace("col_", ""))
                except ValueError:
                    continue
                out[cn] = {"table": str(t.get("TableCol", [""] * n)[i]),
                           "name": str(t.get("DescriptionCol", [""] * n)[i]).strip()}
            if out:
                return out
        except Exception:
            continue
    return out


def read_project_shard_map(accdb_path, year=None):
    """Read the project-ID -> shard routing from the catalog's projet<year>
    table (column `Annees` = '_OdrivDB_1'..). Returns {str(project_id): shard}."""
    from access_parser import AccessParser
    mapping = {}
    tbl = "projet" + str(year) if year else None
    for f in resolve_db_files(accdb_path, year):
        try:
            db = AccessParser(f)
            cand = [tbl] if (tbl and tbl in db.catalog) else \
                   [t for t in db.catalog if t.startswith("projet")
                    and any(ch.isdigit() for ch in t)]
            for tn in cand:
                try:
                    t = db.parse_table(tn)
                except Exception:
                    continue
                if "code" not in t or "Annees" not in t:
                    continue
                codes = t["code"]
                annees = t["Annees"]
                for i in range(len(codes)):
                    a = annees[i]
                    if a:                       # only rows that name a shard
                        mapping[str(codes[i])] = str(a)
            if mapping:
                return mapping
        except Exception:
            continue
    return mapping


def db_exists(path, year=None):
    """True if the CFG path resolves to at least one readable .accdb file."""
    return len(resolve_db_files(path, year)) > 0


# ----------------------------------------------------------------- read side

_PROJECTS_CACHE = {}   # (path, year) -> (timestamp, rows)
_PROJECTS_CACHE_TTL = 60.0   # seconds


def read_projects(accdb_path, year=None, use_cache=True):
    """Return saved-project rows from the `projet` table. `accdb_path` may be a
    single file OR a folder (catalog + year-shards). The project list lives in
    the base catalog's `projet` table, so we read the CATALOG file (the one
    without a numeric suffix, e.g. _OdrivDB.accdb) and stop — we do NOT open the
    big numbered event shards just to list projects (that would be slow over a
    network drive). Results are cached briefly so reopening dialogs is instant."""
    import time as _t
    ckey = (str(accdb_path), str(year))
    if use_cache:
        hit = _PROJECTS_CACHE.get(ckey)
        if hit and (_t.time() - hit[0]) < _PROJECTS_CACHE_TTL:
            return hit[1]
    files = resolve_db_files(accdb_path, year)
    if not files:
        files = [accdb_path]
    # prefer the catalog: a file whose name has no digits (_OdrivDB.accdb)
    catalog_first = sorted(
        files, key=lambda f: any(ch.isdigit() for ch in os.path.basename(f)))
    from access_parser import AccessParser
    out = []
    seen = set()
    for f in catalog_first:
        try:
            db = AccessParser(f)
            if "projet" not in db.catalog:
                continue
            t = db.parse_table("projet")
            cols = list(t.keys())
            n = len(t[cols[0]]) if cols else 0
            for i in range(n):
                rec = {c: t[c][i] for c in cols}
                # dedup on (code, ID, Uniquename): code is the vehicle's true
                # identity (the column header shown to users), so two vehicles
                # with the same ID/Uniquename but different codes are both kept.
                key = (str(rec.get("code")), str(rec.get("ID")),
                       str(rec.get("Uniquename")))
                if key in seen:
                    continue
                seen.add(key)
                rec["_db_file"] = f              # which file it came from
                out.append(rec)
            if out:
                _PROJECTS_CACHE[ckey] = (_t.time(), out)
                return out
        except Exception:
            continue
    if out:
        _PROJECTS_CACHE[ckey] = (_t.time(), out)
    return out


_TABLE_CACHE = {}   # (file_path, table_name) -> parsed table dict


def _disk_cache_path(file_path, table_name):
    import hashlib
    d = os.path.join(os.path.expanduser("~"), ".odriv", "tablecache")
    os.makedirs(d, exist_ok=True)
    try:
        mtime = int(os.path.getmtime(file_path))
        size = os.path.getsize(file_path)
    except OSError:
        mtime, size = 0, 0
    key = hashlib.md5(
        f"{file_path}|{table_name}|{mtime}|{size}".encode()).hexdigest()
    return os.path.join(d, key + ".pkl")


def _parse_table_cached(db, file_path, table_name):
    """Parse a table once per (file, table) and reuse it — in memory for the
    session, and on disk across sessions (keyed by file mtime+size so it
    auto-invalidates if the .accdb changes). The big dataSub tables take ~60s
    each to parse with the pure-Python reader, so this avoids ever paying that
    cost twice for the same data."""
    key = (file_path, table_name)
    cached = _TABLE_CACHE.get(key)
    if cached is not None:
        return cached
    # try disk cache
    import pickle
    dp = _disk_cache_path(file_path, table_name)
    try:
        if os.path.exists(dp):
            with open(dp, "rb") as fh:
                t = pickle.load(fh)
            _TABLE_CACHE[key] = t
            return t
    except Exception:
        pass
    t = db.parse_table(table_name)
    _TABLE_CACHE[key] = t
    try:
        with open(dp, "wb") as fh:
            pickle.dump(t, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return t


def clear_table_cache():
    _TABLE_CACHE.clear()
    _TABLE_INDEX_CACHE.clear()


_TABLE_INDEX_CACHE = {}   # (file_path, table_name) -> {idData: row_position}


def _table_iddata_index(st, file_path, table_name):
    """Build (and cache) a map idData-value -> row position for a parsed sub
    table, so a project's rows are fetched by direct lookup instead of scanning
    all ~95k rows on every read."""
    key = (file_path, table_name)
    idx = _TABLE_INDEX_CACHE.get(key)
    if idx is not None:
        return idx
    idx = {}
    for pos, idd in enumerate(st.get("idData", [])):
        idx[idd] = pos
    _TABLE_INDEX_CACHE[key] = idx
    return idx


_LAST_READ_INFO = {"method": None, "detail": None, "seconds": None}


def get_last_read_info():
    return dict(_LAST_READ_INFO)


def _read_events_jdbc(accdb_file, keys):
    """Fast path: read one project's events via UCanAccess (JDBC) using a WHERE
    query, so only that project's ~2k rows are read instead of parsing the whole
    95k-row dataSub tables in Python. Returns the events list, or None if the
    JDBC driver/Java isn't available (caller falls back to the pure-Python read).

    keys = set of strings to match against dataId.UniqueName (project ID and/or
    Uniquename)."""
    import time as _t
    _start = _t.time()
    if not java_available():
        _LAST_READ_INFO.update(method="python", detail="java not found",
                               seconds=None)
        return None
    try:
        import jaydebeapi
        cp = ensure_ucanaccess()
    except Exception as e:
        _LAST_READ_INFO.update(method="python",
                               detail="jdbc driver unavailable: %s" % e,
                               seconds=None)
        return None
    conn = None
    try:
        url = ("jdbc:ucanaccess://" + accdb_file +
               ";memory=false;singleConnection=true;newDatabaseVersion=V2010")
        conn = jaydebeapi.connect(
            "net.ucanaccess.jdbc.UcanaccessDriver", url, [], cp)
        cur = conn.cursor()
        # which dataId rows belong to this project
        intkeys = [k for k in keys if str(k).isdigit()]
        strkeys = [k for k in keys if not str(k).isdigit()]
        clauses, params = [], []
        if intkeys:
            clauses.append("UniqueName IN (%s)" % ",".join(intkeys))
        for sk in strkeys:
            clauses.append("UniqueName = ?")
            params.append(sk)
        if not clauses:
            return []
        cur.execute('SELECT [N\u00b0], [Sous situation de vie, Sub Event Name] '
                    'FROM dataId WHERE ' + " OR ".join(clauses), params)
        want = {}
        for row in cur.fetchall():
            want[row[0]] = row[1]
        if not want:
            return []
        events_by_id = {k: {"sdv": v} for k, v in want.items()}
        id_list = ",".join(str(int(k)) for k in want.keys())
        for tn in ("dataSub1", "dataSub2", "dataSub3"):
            try:
                cur.execute("SELECT * FROM %s WHERE idData IN (%s)" % (tn, id_list))
                cols = [d[0] for d in cur.description]
                idpos = cols.index("idData") if "idData" in cols else 0
                colpos = [(i, c) for i, c in enumerate(cols)
                          if str(c).startswith("col_")]
                for row in cur.fetchall():
                    idd = row[idpos]
                    tgt = events_by_id.get(idd)
                    if tgt is not None:
                        for i, c in colpos:
                            if row[i] is not None:
                                tgt[c] = row[i]
            except Exception:
                continue
        _LAST_READ_INFO.update(method="jdbc", detail="ok",
                               seconds=round(_t.time() - _start, 1))
        return list(events_by_id.values())
    except Exception as e:
        _LAST_READ_INFO.update(method="python",
                               detail="jdbc failed: %s" % str(e)[:200],
                               seconds=None)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def read_project_events(accdb_path, project_id, db_file=None, year=None):
    """Return the events (channel dicts) belonging to one project ID.

    Storage is split: the base `_OdrivDB.accdb` holds the project
    CATALOG (`projet`), while the EVENTS (`dataId`/`dataSub`) live in the sharded
    `<year>\\_OdrivDB_1..4.accdb`. So the file that holds a project's `projet`
    row is NOT the file that holds its events. We therefore try the hinted file
    first, then fall back to EVERY resolved shard until we find the events.
    Matching is by the project's UniqueName (preferred) or numeric ID.
    """
    all_files = resolve_db_files(accdb_path, year)
    # consult the catalog's project->shard routing (projet<year>.Annees) so we
    # go straight to the shard that holds this project's events.
    routed = None
    try:
        smap = read_project_shard_map(accdb_path, year)
        shard_name = smap.get(str(project_id))      # e.g. "_OdrivDB_1"
        if shard_name:
            for f in all_files:
                if os.path.basename(f).startswith(shard_name):
                    routed = f
                    break
    except Exception:
        routed = None
    # search order: routed shard, then hinted file, then all shards (deduped)
    search = []
    for f in (routed, db_file):
        if f and os.path.isfile(f) and f not in search:
            search.append(f)
    for f in all_files:
        if f not in search:
            search.append(f)
    if not search and accdb_path:
        search = [accdb_path]

    # resolve the project's UniqueName from whichever catalog file has the row,
    # so we can match events even if dataId keys on UniqueName text vs numeric ID
    uniquename = None
    try:
        for p in read_projects(accdb_path, year):
            if str(p.get("ID")) == str(project_id):
                uniquename = p.get("Uniquename")
                break
    except Exception:
        pass

    from access_parser import AccessParser
    keys = {str(project_id)}
    if uniquename:
        keys.add(str(uniquename))

    # FAST PATH: try a targeted JDBC WHERE-query read first (reads only this
    # project's rows). Falls through to the pure-Python parse if Java/JDBC isn't
    # available or the query fails.
    for f in search:
        ev = _read_events_jdbc(f, keys)
        if ev:                              # found this project's events via JDBC
            return ev

    for f in search:
        try:
            db = AccessParser(f)
            did = _parse_table_cached(db, f, "dataId")
        except Exception:
            continue
        idcols = list(did.keys())
        n = len(did[idcols[0]]) if idcols else 0
        if n == 0:
            continue
        # dataId.UniqueName may store the project ID or its Uniquename string
        uname_col = did.get("UniqueName", [None] * n)
        sename_col = did.get("Sous situation de vie, Sub Event Name", [None] * n)
        want = {}
        for i in range(n):
            if str(uname_col[i]) in keys:
                want[did["N\u00b0"][i]] = sename_col[i]
        if not want:
            continue                       # events not in this shard; try next
        sub_tables = []
        for tn in ("dataSub1", "dataSub2", "dataSub3"):
            try:
                st = _parse_table_cached(db, f, tn)
                if st and len(next(iter(st.values()))) > 0:
                    sub_tables.append((tn, st))
            except Exception:
                continue
        # find the row positions for this project's events in one pass, then copy
        # only those rows' channel values (avoids re-scanning per channel).
        events_by_id = {k: {"sdv": v} for k, v in want.items()}
        wanted = set(want.keys())
        for tn, st in sub_tables:
            scols = [c for c in st.keys() if c.startswith("col_")]
            id_list = st.get("idData", [])
            # positions of the rows we need
            positions = [(idd, j) for j, idd in enumerate(id_list)
                         if idd in wanted]
            for c in scols:
                col = st[c]
                for idd, j in positions:
                    v = col[j]
                    if v is not None:
                        events_by_id[idd][c] = v
        return list(events_by_id.values())
    return []


# ----------------------------------------------------------------- write side

def _jar_dir():
    d = os.path.join(os.path.expanduser("~"), ".odriv", "ucanaccess")
    os.makedirs(d, exist_ok=True)
    return d


# mirrors to try for each jar, in order. Corporate networks often block
# repo1.maven.org but allow one of the others (or an internal Nexus/Artifactory).
_JAR_MIRRORS = [
    "https://repo1.maven.org/maven2/",
    "https://repo.maven.apache.org/maven2/",
    "https://maven-central.storage-download.googleapis.com/maven2/",
    "https://repository.jboss.org/nexus/content/repositories/central/",
]

# (filename, maven path) — the path is appended to each mirror base
_UCANACCESS_PATHS = [
    ("ucanaccess-5.0.1.jar",
     "net/sf/ucanaccess/ucanaccess/5.0.1/ucanaccess-5.0.1.jar"),
    ("jackcess-4.0.1.jar",
     "com/healthmarketscience/jackcess/jackcess/4.0.1/jackcess-4.0.1.jar"),
    ("commons-lang3-3.8.1.jar",
     "org/apache/commons/commons-lang3/3.8.1/commons-lang3-3.8.1.jar"),
    ("commons-logging-1.2.jar",
     "commons-logging/commons-logging/1.2/commons-logging-1.2.jar"),
    ("hsqldb-2.5.0.jar",
     "org/hsqldb/hsqldb/2.5.0/hsqldb-2.5.0.jar"),
]


def ucanaccess_jar_dir():
    """Public: the folder where the UCanAccess jars live / can be placed by hand."""
    return _jar_dir()


def ucanaccess_status():
    """Report whether the JDBC driver jars are present (so the UI/diagnostics can
    tell the user the fast path is or isn't available, without trying a read)."""
    d = _jar_dir()
    have = []
    missing = []
    for fn, _ in _UCANACCESS_PATHS:
        p = os.path.join(d, fn)
        (have if (os.path.exists(p) and os.path.getsize(p) > 1000)
         else missing).append(fn)
    return {"dir": d, "present": have, "missing": missing,
            "ready": not missing and java_available(),
            "java": java_available()}


def ensure_ucanaccess():
    """Ensure the UCanAccess jars are available; return the classpath list.
    Tries each mirror in turn. Raises RuntimeError with precise manual-install
    guidance if none work (e.g. a locked-down corporate network)."""
    d = _jar_dir()
    paths = []
    errors = []
    for fn, mpath in _UCANACCESS_PATHS:
        p = os.path.join(d, fn)
        if not os.path.exists(p) or os.path.getsize(p) < 1000:
            ok = False
            for base in _JAR_MIRRORS:
                try:
                    req = urllib.request.Request(
                        base + mpath, headers={"User-Agent": "odriv/1.0"})
                    with urllib.request.urlopen(req, timeout=20) as r, \
                            open(p, "wb") as fh:
                        fh.write(r.read())
                    if os.path.getsize(p) > 1000:
                        ok = True
                        break
                except Exception as e:
                    errors.append("%s: %s" % (base.split("/")[2], e))
                    continue
            if not ok:
                raise RuntimeError(
                    "Could not download the fast Access reader (UCanAccess jars). "
                    "Your network may block the Maven repositories. To enable the "
                    "fast database read, place these 5 jars in:\n  " + d +
                    "\n  " + ", ".join(fn for fn, _ in _UCANACCESS_PATHS) +
                    "\n(They are standard Maven Central artifacts; your IT/Nexus "
                    "likely has them.) Until then the slower built-in reader is "
                    "used. Tried: " + "; ".join(errors[:4]))
        paths.append(p)
    return paths


def _connect(accdb_path):
    import jaydebeapi
    cp = ensure_ucanaccess()
    url = "jdbc:ucanaccess://" + accdb_path + ";newDatabaseVersion=V2010"
    return jaydebeapi.connect(
        "net.ucanaccess.jdbc.UcanaccessDriver", url, [], cp)


def java_available():
    import shutil
    return shutil.which("java") is not None


def _count_projects(accdb_file):
    """Count rows in a shard's `projet` table (for the load balancer)."""
    try:
        from access_parser import AccessParser
        t = AccessParser(accdb_file).parse_table("projet")
        cols = list(t.keys())
        return len(t[cols[0]]) if cols else 0
    except Exception:
        return 0


def choose_write_shard(path, year=None):
    """Pick which event shard to write into, mirroring the Excel balancer:
    the numbered shard with the fewest projects (and < 50); else the last shard.
    Only numbered _OdrivDB_<N> shards are candidates (the base catalog is not an
    event store). If `path` is a single file, returns it directly."""
    files = [f for f in resolve_db_files(path, year)
             if any(ch.isdigit() for ch in os.path.basename(f))] or \
            resolve_db_files(path, year)
    if not files:
        raise RuntimeError(
            "No _OdrivDB_*.accdb found at: " + str(path) +
            " (on VPN, check the shared drive is mapped).")
    if len(files) == 1:
        return files[0]
    best, best_count = None, 51
    for f in files:
        c = _count_projects(f)
        if c < best_count and c < 50:
            best_count, best = c, f
    return best or files[-1]


def write_project(accdb_path, projet_row, events, header_to_colnum, year=None):
    """Insert a processed project into the shared .accdb in the Excel schema.
    `accdb_path` may be a folder (the least-full shard is chosen, like the Excel
    load balancer) or a direct .accdb file.

    projet_row       : dict with the 17 `projet` columns (ID may be None -> max+1)
    events           : list of {"sdv": name, channels...} dicts
    header_to_colnum : {acquisition header -> col_N index 1..742} mapping so each
                       channel value lands in the right dataSub column.
    Returns (new project ID, shard file written to).
    """
    target_file = choose_write_shard(accdb_path, year)
    conn = _connect(target_file)
    try:
        cur = conn.cursor()
        # next project ID
        cur.execute("SELECT MAX(ID) FROM projet")
        row = cur.fetchone()
        pid = (row[0] or 150) + 1 if row else 151
        # insert projet row
        cols = ["ID", "DateCreation", "code", "droopy", "gears", "energy",
                "priority", "milestone", "aera", "target", "software",
                "target_vehicle", "Version", "Mode", "Uniquename", "NbGear",
                "ColonneDb"]
        vals = [pid] + [projet_row.get(c) for c in cols[1:]]
        ph = ",".join(["?"] * len(cols))
        cur.execute(f"INSERT INTO projet ({','.join(cols)}) VALUES ({ph})", vals)
        # next dataId N°
        cur.execute("SELECT MAX([N\u00b0]) FROM dataId")
        r2 = cur.fetchone()
        nbase = (r2[0] or 0) if r2 else 0
        # insert each event into dataId + the three dataSub tables
        for k, ev in enumerate(events, start=1):
            ndata = nbase + k
            cur.execute(
                "INSERT INTO dataId ([N\u00b0], UniqueName, code, "
                "[Sous situation de vie, Sub Event Name]) VALUES (?,?,?,?)",
                [ndata, pid, projet_row.get("code"), ev.get("sdv")])
            # split channel values across dataSub1/2/3 by col number
            buckets = {1: {}, 2: {}, 3: {}}
            for header, val in ev.items():
                if header == "sdv":
                    continue
                cn = header_to_colnum.get(header)
                if cn is None:
                    continue
                b = 1 if cn <= 255 else (2 if cn <= 500 else 3)
                buckets[b][f"col_{cn}"] = val
            for b, tbl in ((1, "dataSub1"), (2, "dataSub2"), (3, "dataSub3")):
                data = buckets[b]
                colnames = ["[N\u00b0]", "idData"] + [f"[{c}]" for c in data]
                placeh = ",".join(["?"] * len(colnames))
                cur.execute(
                    f"INSERT INTO {tbl} ({','.join(colnames)}) VALUES ({placeh})",
                    [ndata, ndata] + list(data.values()))
        conn.commit()
        return pid, target_file
    finally:
        conn.close()
