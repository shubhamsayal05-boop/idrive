"""ODRIV backend — FastAPI service for the Objective Drivability scorecard tool."""
import json
import os
import io
import logging
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, APIRouter, HTTPException, UploadFile, File, Body
from fastapi.responses import FileResponse
from motor.motor_asyncio import AsyncIOMotorClient
from starlette.middleware.cors import CORSMiddleware

from engine import config_loader, scoring, importer
from engine.classifier import classify_event, get_channel
from engine import reports as report_builder
from engine import docx_report as docx_builder

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ.get('DB_NAME', 'odriv')]

app = FastAPI(title="ODRIV")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("odriv")

ODRIV_VERSION = "ODRIV (Python)"

PROJECT_FIELDS = ["name_code", "mode", "fuel", "gears", "gearbox", "droopy",
                  "software_milestone", "priority", "version",
                  "odriv_milestone", "area", "target_vehicle",
                  "number_of_gears", "eval_mode"]


# --------------------------------------------------------------- helpers

async def moniteur(msg):
    """Macro_Log equivalent."""
    await db.macro_log.insert_one({
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "message": msg})


async def get_config(section=None):
    if section:
        doc = await db.config.find_one({"section": section}, {"_id": 0})
        if not doc:
            raise HTTPException(404, f"Unknown config section {section}")
        return doc["data"]
    cfg = {}
    async for doc in db.config.find({}, {"_id": 0}):
        cfg[doc["section"]] = doc["data"]
    return cfg


async def get_project():
    return await db.project.find_one({}, {"_id": 0})


def canon_map_of(cfg):
    return config_loader.build_canon_map(cfg["structure"], cfg["catalog"])


async def seed_if_needed(force=False):
    count = await db.config.count_documents({})
    if count > 0 and not force:
        return
    await db.config.delete_many({})
    sections = config_loader.load_seed_sections()
    for name, data in sections.items():
        await db.config.insert_one({"section": name, "data": data})
    await moniteur("Configuration seeded from ODRIV_v29_2_1_AT workbook")
    logger.info("Seeded %d config sections", len(sections))


@app.on_event("startup")
async def startup():
    await seed_if_needed()


# --------------------------------------------------------------- state

@api.get("/state")
async def state():
    project = await get_project()
    cfg_catalog = await get_config("catalog")
    pipeline = [{"$match": {"sdv": {"$ne": ""}}},
                {"$group": {"_id": "$sdv", "n": {"$sum": 1}}}]
    counts = {d["_id"]: d["n"] async for d in db.events.aggregate(pipeline)}
    order = {c["name"]: c["order"] for c in cfg_catalog}
    sheets = [{"name": k, "events": v} for k, v in counts.items() if v > 2]
    sheets.sort(key=lambda s: order.get(s["name"], 999))
    total_events = await db.events.count_documents({})
    rating = await db.rating_global.find_one({}, {"_id": 0})
    logs = await db.macro_log.find({}, {"_id": 0}).sort("ts", -1).limit(5).to_list(5)
    return {"project": project, "sheets": sheets, "total_events": total_events,
            "has_rating": rating is not None, "version": ODRIV_VERSION,
            "log_tail": logs}


# --------------------------------------------------------------- project

@api.post("/project/new")
async def new_project(payload: dict = Body(...)):
    await _erase_all()
    project = {f: payload.get(f) for f in PROJECT_FIELDS}
    project["id"] = str(uuid.uuid4())
    project["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.project.insert_one(dict(project))
    await moniteur(f"New project has been created : {project.get('name_code')}")
    project.pop("_id", None)
    return project


@api.put("/project")
async def update_project(payload: dict = Body(...)):
    project = await get_project()
    if not project:
        raise HTTPException(400, "No project. Use NEW PROJECT first.")
    updates = {k: v for k, v in payload.items() if k in PROJECT_FIELDS}
    await db.project.update_one({"id": project["id"]}, {"$set": updates})
    if "version" in updates or "fuel" in updates:
        await moniteur("Targets have been updated (drive version / fuel changed)")
    return await get_project()


async def _erase_all():
    await db.events.delete_many({})
    await db.sdv_results.delete_many({})
    await db.rating_global.delete_many({})
    await db.project.delete_many({})


@api.delete("/project")
async def erase_all():
    await _erase_all()
    await moniteur("ERASE ALL DATA : project deleted")
    return {"ok": True}


# --------------------------------------------------------------- import

async def _store_events(parsed, filename, cfg):
    canon = canon_map_of(cfg)
    rules = cfg["definitions"]
    docs = []
    per_sdv = {}
    unclassified = 0
    for channels in parsed:
        sdv = classify_event(channels, rules)
        name = config_loader.canon_name(sdv, canon) if sdv else ""
        if not name:
            unclassified += 1
        else:
            per_sdv[name] = per_sdv.get(name, 0) + 1
        docs.append({"id": str(uuid.uuid4()), "sdv": name, "channels": channels,
                     "file": filename,
                     "imported_at": datetime.now(timezone.utc).isoformat()})
    if docs:
        await db.events.insert_many(docs)
    return {"imported": len(docs), "classified": len(docs) - unclassified,
            "unclassified": unclassified, "per_sdv": per_sdv}


@api.post("/import/file")
async def import_file(file: UploadFile = File(...)):
    project = await get_project()
    if not project:
        raise HTTPException(400, "Project information missing. Create a project first.")
    missing = [f for f in ("fuel", "gears", "software_milestone", "odriv_milestone")
               if not project.get(f)]
    if missing:
        raise HTTPException(400, "Project information missing : " + ", ".join(missing))
    content = await file.read()
    try:
        parsed, _ = importer.parse_trie(content)
    except ValueError as e:
        raise HTTPException(400, str(e))
    cfg = await get_config()
    result = await _store_events(parsed, file.filename, cfg)
    await moniteur(f"File {file.filename} has been added to your project "
                   f"({result['classified']}/{result['imported']} events classified)")
    return result


@api.post("/import/demo")
async def import_demo():
    project = await get_project()
    if not project:
        raise HTTPException(400, "Project information missing. Create a project first.")
    cfg = await get_config()
    canon = canon_map_of(cfg)
    events = importer.generate_sample_events(cfg["definitions"], cfg["structure"], canon)
    result = await _store_events(events, "DEMO_ACQUISITION.xlsx", cfg)
    await moniteur(f"Demo acquisition generated and added "
                   f"({result['classified']}/{result['imported']} events classified)")
    return result


@api.get("/import/sample")
async def download_sample():
    cfg = await get_config()
    canon = canon_map_of(cfg)
    events = importer.generate_sample_events(cfg["definitions"], cfg["structure"], canon)
    path = os.path.join(tempfile.gettempdir(), "ODRIV_sample_acquisition.xlsx")
    importer.write_sample_workbook(path, events)
    return FileResponse(path, filename="ODRIV_sample_acquisition.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --------------------------------------------------------------- rating

_CALC_PROGRESS = {"running": False, "percent": 0, "phase": "", "done": False,
                  "error": None, "sdv_count": 0}


def _set_progress(percent=None, phase=None, **kw):
    if percent is not None:
        _CALC_PROGRESS["percent"] = max(0, min(100, int(percent)))
    if phase is not None:
        _CALC_PROGRESS["phase"] = phase
    _CALC_PROGRESS.update(kw)


async def _run_calculation():
    """Do the full rating calculation, updating _CALC_PROGRESS as it goes so the
    UI can show a percentage. Scoring + persistence is the first ~40%; the rest
    is divided across the comparison vehicles (the slow .accdb reads)."""
    try:
        _set_progress(2, "Loading events…", running=True, done=False, error=None)
        project = await get_project()
        if not project:
            raise RuntimeError("No project")
        cfg = await get_config()
        events = await db.events.find({"sdv": {"$ne": ""}}, {"_id": 0}).to_list(100000)
        if not events:
            raise RuntimeError("No events in database. Add a file first.")
        canon = canon_map_of(cfg)

        # Calculate scores ONLY the current project vehicle. Target vehicles are
        # NOT read or scored here — their columns stay empty until the user
        # presses "Set as target" on the RATING tab. So we clear any previously
        # resolved target data and blank the per-SDV target column.
        tv = await get_config("target_vehicle")
        tv["multi"] = {}
        tv["targets"] = []
        tv["rows"] = []                 # empty target column until "Set as target"
        await db.config.update_one({"section": "target_vehicle"},
                                   {"$set": {"data": tv}})
        cfg = await get_config()

        _set_progress(35, "Scoring maneuvers…")
        targets_lookup = config_loader.build_targets_lookup(cfg["targets"], project)
        updates, sdv_results, global_results = scoring.calculate_rating(
            project, events, cfg, targets_lookup, canon)

        _set_progress(80, "Saving event scores…")
        if updates:
            scored = await db.events.find({}, {"_id": 0}).to_list(100000)
            for e in scored:
                parts = updates.get(e.get("id"))
                if parts:
                    e.update(parts)
            await db.events.delete_many({})
            if scored:
                await db.events.insert_many(scored)
        await db.sdv_results.delete_many({})
        if sdv_results:
            await db.sdv_results.insert_many([dict(r) for r in sdv_results])
        global_results["calculated_at"] = datetime.now(timezone.utc).isoformat()
        await db.rating_global.delete_many({})
        await db.rating_global.insert_one(dict(global_results))
        _CALC_PROGRESS["sdv_count"] = len(sdv_results)

        _set_progress(100, "Done", running=False, done=True)
        await moniteur("Rating has been calculated.")
    except Exception as e:
        _set_progress(phase=f"Error: {e}", running=False, done=True,
                      error=str(e))


@api.post("/rating/calculate/start")
async def calculate_rating_start():
    """Kick off the calculation in the background and return immediately. The UI
    then polls /rating/progress for the percentage. Use this for the progress
    popup; /rating/calculate (below) still runs synchronously for callers that
    want to block."""
    if _CALC_PROGRESS.get("running"):
        return {"ok": True, "already_running": True}
    project = await get_project()
    if not project:
        raise HTTPException(400, "No project")
    _set_progress(0, "Starting…", running=True, done=False, error=None,
                  sdv_count=0)
    import asyncio
    asyncio.create_task(_run_calculation())
    return {"ok": True, "started": True}


@api.get("/rating/progress")
async def calculate_rating_progress():
    """Current calculation progress for the popup (percent 0-100, phase text)."""
    return dict(_CALC_PROGRESS)


@api.post("/rating/calculate")
async def calculate_rating():
    project = await get_project()
    if not project:
        raise HTTPException(400, "No project")
    cfg = await get_config()
    events = await db.events.find({"sdv": {"$ne": ""}}, {"_id": 0}).to_list(100000)
    if not events:
        raise HTTPException(400, "No events in database. Add a file first.")
    canon = canon_map_of(cfg)
    # Calculate scores ONLY the current vehicle. Clear any target data so the
    # target columns are empty until the user presses "Set as target".
    tv = await get_config("target_vehicle")
    tv["multi"] = {}
    tv["targets"] = []
    tv["rows"] = []
    await db.config.update_one({"section": "target_vehicle"},
                               {"$set": {"data": tv}})
    cfg = await get_config()
    targets_lookup = config_loader.build_targets_lookup(cfg["targets"], project)
    updates, sdv_results, global_results = scoring.calculate_rating(
        project, events, cfg, targets_lookup, canon)
    # persist event scores fast: merge the computed parts into the in-memory
    # event docs and rewrite the collection in two bulk ops (delete_many +
    # insert_many) instead of thousands of awaited update_one calls. This is the
    # main speed fix on large acquisitions (was ~12s, now well under 1s).
    if updates:
        scored = await db.events.find({}, {"_id": 0}).to_list(100000)
        for e in scored:
            parts = updates.get(e.get("id"))
            if parts:
                e.update(parts)
        await db.events.delete_many({})
        if scored:
            await db.events.insert_many(scored)
    await db.sdv_results.delete_many({})
    if sdv_results:
        await db.sdv_results.insert_many([dict(r) for r in sdv_results])
    global_results["calculated_at"] = datetime.now(timezone.utc).isoformat()
    await db.rating_global.delete_many({})
    await db.rating_global.insert_one(dict(global_results))
    await moniteur("Rating has been calculated.")
    global_results.pop("_id", None)
    return {"global": global_results, "sdv_count": len(sdv_results)}


@api.get("/rating")
async def get_rating():
    project = await get_project()
    glob = await db.rating_global.find_one({}, {"_id": 0})
    rows = await db.sdv_results.find({}, {"_id": 0}).sort("order", 1).to_list(200)
    catalog = await get_config("catalog")
    # multi-target comparison columns (one per selected vehicle), if any
    tv = await get_config("target_vehicle")
    targets = (tv or {}).get("targets") or []
    multi = (tv or {}).get("multi") or {}
    try:
        gpuiss = (await get_config())["settings_global"]["constants"]["GLOBALPUISS"]
    except Exception:
        gpuiss = 5
    # shape: {vehicle: {SDV_UPPER: {driv, dyn}}}
    comparisons = {}
    target_globals = {}     # {vehicle: {driv, dyn, driv_pos, dyn_pos, ...}}
    for veh, vrows in multi.items():
        comparisons[veh] = {r["sdv"].strip().upper():
                            {"driv": r.get("driv"), "dyn": r.get("dyn")}
                            for r in vrows}
        # the per-vehicle global index is stashed on the first row by
        # _resolve_target_rows so we can place its marker on the index bar
        gd = next((r.get("_global_driv") for r in vrows
                   if r.get("_global_driv") is not None), None)
        gy = next((r.get("_global_dyn") for r in vrows
                   if r.get("_global_dyn") is not None), None)
        # "Weighted % of events below target" (rate_low) per part, if scored
        rld = next((r.get("_rate_low_driv") for r in vrows
                    if r.get("_rate_low_driv") is not None), None)
        rly = next((r.get("_rate_low_dyn") for r in vrows
                    if r.get("_rate_low_dyn") is not None), None)
        _pos = lambda v: (round(((v / 100.0) ** gpuiss) * 100, 2)
                          if v is not None else None)
        target_globals[veh] = {
            "driv": gd, "dyn": gy,
            "driv_pos": _pos(gd), "dyn_pos": _pos(gy),
            "rate_low_driv": rld, "rate_low_dyn": rly,
            "taux_driv_pos": round(rld * 100, 3) if rld is not None else None,
            "taux_dyn_pos": round(rly * 100, 3) if rly is not None else None}
    return {"project": project, "global": glob, "rows": rows, "catalog": catalog,
            "version": ODRIV_VERSION, "targets": targets,
            "comparisons": comparisons, "target_globals": target_globals}


_TARGET_PROGRESS = {"running": False, "percent": 0, "phase": "", "done": False,
                    "error": None, "read_method": None, "read_detail": None}


def _set_tprogress(percent=None, phase=None, **kw):
    if percent is not None:
        _TARGET_PROGRESS["percent"] = max(0, min(100, int(percent)))
    if phase is not None:
        _TARGET_PROGRESS["phase"] = phase
    _TARGET_PROGRESS.update(kw)


async def _run_set_targets():
    """Read + score the selected target vehicle(s) (the pending list set in New
    Project) and populate the target columns + the per-vehicle 'multi' data used
    by the RATING graph. This is where the (possibly slow) .accdb read happens —
    only when the user presses 'Set as target'."""
    try:
        _set_tprogress(3, "Preparing…", running=True, done=False, error=None)
        tv = await get_config("target_vehicle")
        pend = (tv or {}).get("pending") or []
        if not pend:
            _set_tprogress(100, "No target vehicles selected.", running=False,
                           done=True)
            return
        try:
            from engine import accdb_bridge as _ab
            if any(t.get("source") == "accdb" for t in pend):
                _TARGET_PROGRESS["read_method"] = (
                    "jdbc" if _ab.java_available() else "python")
        except Exception:
            pass
        multi, labels = {}, []
        primary_rows = None
        span = 92.0 / max(1, len(pend))
        for i, t in enumerate(pend):
            lbl = t.get("label") or f"vehicle {i+1}"
            _set_tprogress(4 + int(i * span),
                           f"Reading & scoring target vehicle: {lbl} "
                           f"({i+1}/{len(pend)})…")
            try:
                # reference vehicles are identified by their label; accdb
                # vehicles by a composite (code + uniquename + id) so two
                # distinct vehicles never collide even if their ID is shared
                # or null in the shared database.
                if t.get("source") == "ref":
                    ident = t.get("label")
                elif t.get("source") in ("accdb", "sqlite"):
                    ident = {"id": t.get("id"), "code": t.get("label"),
                             "uniquename": t.get("uniquename"),
                             "db_file": t.get("db_file")}
                else:
                    ident = t.get("id")
                vehicle, rows = await _resolve_target_rows(t.get("source"), ident)
                labels.append(vehicle)
                multi[vehicle] = {r["sdv"].strip().upper(): r for r in rows}
                if i == 0:
                    primary_rows = rows
                if t.get("source") == "accdb":
                    info = _ab.get_last_read_info()
                    if info.get("method"):
                        _TARGET_PROGRESS["read_method"] = info["method"]
                        _TARGET_PROGRESS["read_detail"] = info.get("detail")
            except Exception:
                continue
        if multi:
            tv["multi"] = {v: list(rm.values()) for v, rm in multi.items()}
            tv["targets"] = labels
            # the per-SDV target column shows the PRIMARY (first) selected target
            if primary_rows is not None:
                tv["rows"] = [dict(r) for r in primary_rows]
            await db.config.update_one({"section": "target_vehicle"},
                                       {"$set": {"data": tv}})
            await moniteur("SET AS TARGET : scored target vehicle(s): "
                           + ", ".join(labels))
        _set_tprogress(100, "Done", running=False, done=True)
    except Exception as e:
        _set_tprogress(phase=f"Error: {e}", running=False, done=True,
                       error=str(e))


@api.post("/rating/set-as-target/start")
async def set_as_target_start():
    """Kick off scoring of the selected target vehicle(s) in the background.
    The UI polls /rating/set-as-target/progress."""
    if _TARGET_PROGRESS.get("running"):
        return {"ok": True, "already_running": True}
    tv = await get_config("target_vehicle")
    pend = (tv or {}).get("pending") or []
    if not pend:
        raise HTTPException(400, "No target vehicles selected for this project.")
    _set_tprogress(0, "Starting…", running=True, done=False, error=None)
    import asyncio
    asyncio.create_task(_run_set_targets())
    return {"ok": True, "started": True, "count": len(pend)}


@api.get("/rating/set-as-target/progress")
async def set_as_target_progress():
    return dict(_TARGET_PROGRESS)


@api.post("/rating/set-as-target")
async def set_as_target():
    """Synchronous fallback: read + score the selected target vehicle(s) now."""
    tv = await get_config("target_vehicle")
    pend = (tv or {}).get("pending") or []
    if not pend:
        raise HTTPException(400, "No target vehicles selected for this project.")
    await _run_set_targets()
    if _TARGET_PROGRESS.get("error"):
        raise HTTPException(500, _TARGET_PROGRESS["error"])
    tv2 = await get_config("target_vehicle")
    return {"ok": True, "targets": tv2.get("targets", [])}


# ------------------------------------------------ saved-projects database
# Reads the source tool's Access DB (_OdrivDB_*.accdb): each processed project
# is persisted as a distinct record (Access `projet` table shape) with its
# scorecard + events snapshot, so it can be browsed, reopened, and compared.

@api.post("/db/save")
async def db_save_project():
    """Save the current processed project into the saved-projects database,
    writing a row to the Access `projet` table."""
    from engine import projects_db
    project = await get_project()
    if not project:
        raise HTTPException(400, "No project to save. Create a project first.")
    glob = await db.rating_global.find_one({}, {"_id": 0})
    if not glob:
        raise HTTPException(400, "Calculate the rating before saving to the database.")
    sdv_rows = await db.sdv_results.find({}, {"_id": 0}).to_list(200)
    events = await db.events.find({}, {"_id": 0}).to_list(100000)
    cfg = await get_config()
    m_idx = scoring.milestone_index(project, cfg["configurations"])
    milestone_num = m_idx + 1
    per_sdv = {}
    for e in events:
        if e.get("sdv"):
            per_sdv[e["sdv"]] = per_sdv.get(e["sdv"], 0) + 1
    record = projects_db.project_to_record(
        project, milestone_num, sdv_rows, glob, len(events), per_sdv)
    # attach the full events + sdv results snapshot (the dataId/dataSub payload)
    record["_events"] = events
    record["_sdv_results"] = sdv_rows
    # store the global driv/dyn index too, so when this project is later used as a
    # TARGET vehicle its marker + summary index can be shown on the RATING graph
    record["_global"] = glob
    # upsert on Uniquename so re-saving the same project updates it (Excel does
    # the same — Uniquename is the natural key)
    existing = await db.projets.find_one({"Uniquename": record["Uniquename"]},
                                         {"_id": 0, "id": 1})
    if existing:
        record["id"] = existing["id"]
        await db.projets.replace_one({"Uniquename": record["Uniquename"]}, record)
        action = "updated"
    else:
        await db.projets.insert_one(record)
        action = "saved"
    # Also write into the configured SQLite database (if any), so the project
    # joins the shared vehicle pool and is selectable as a target later.
    sqlite_note = ""
    try:
        import asyncio
        from engine import sqlite_bridge
        spath = await _shared_accdb_path()
        if spath and (sqlite_bridge.db_exists(spath) or os.path.isdir(spath)):
            code, n = await asyncio.to_thread(
                sqlite_bridge.write_project, spath, record, events)
            sqlite_note = f" (and into the SQLite database: {n} events)"
            await moniteur(f"Project written to SQLite database : {code} "
                           f"({n} events)")
    except Exception as e:
        sqlite_note = f" (SQLite save skipped: {e})"
    await moniteur(f"Project {action} to database : {record['code']} "
                   f"({record['Uniquename']}){sqlite_note}")
    return {"ok": True, "action": action, "id": record["id"],
            "uniquename": record["Uniquename"]}


@api.get("/db/projects")
async def db_list_projects():
    """List all saved projects (Access `projet` table rows), newest first."""
    from engine import projects_db
    rows = await db.projets.find(
        {}, {"_id": 0, "_events": 0, "_sdv_results": 0}).to_list(1000)
    rows.sort(key=lambda r: r.get("DateCreation", ""), reverse=True)
    return {"projects": rows, "columns": projects_db.PROJET_COLUMNS,
            "total": len(rows)}


@api.get("/db/projects/{pid}")
async def db_get_project(pid: str):
    """Full saved record incl. events + scorecard (for preview/compare)."""
    rec = await db.projets.find_one({"id": pid}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Saved project not found")
    return rec


@api.post("/db/projects/{pid}/load")
async def db_load_project(pid: str):
    """Reopen a saved project: restore it as the active project with its events
    and scorecard, exactly like opening a record from the Access database."""
    rec = await db.projets.find_one({"id": pid}, {"_id": 0})
    if not rec:
        raise HTTPException(404, "Saved project not found")
    await _erase_all()
    project = dict(rec.get("project") or {})
    project["id"] = str(uuid.uuid4())
    project["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.project.insert_one(dict(project))
    events = rec.get("_events") or []
    if events:
        # refresh ids to avoid collisions, keep all classification + scores
        for e in events:
            e.pop("_id", None)
        await db.events.insert_many([dict(e) for e in events])
    sdv_rows = rec.get("_sdv_results") or []
    if sdv_rows:
        await db.sdv_results.insert_many([dict(r) for r in sdv_rows])
    if rec.get("global"):
        g = dict(rec["global"])
        g.pop("_id", None)
        await db.rating_global.insert_one(g)
    await moniteur(f"Project loaded from database : {rec.get('code')}")
    project.pop("_id", None)
    return {"ok": True, "project": project, "event_count": len(events),
            "sdv_count": len(sdv_rows)}


@api.delete("/db/projects/{pid}")
async def db_delete_project(pid: str):
    rec = await db.projets.find_one({"id": pid}, {"_id": 0, "code": 1})
    res = await db.projets.delete_one({"id": pid})
    if res.deleted_count:
        await moniteur(f"Project removed from database : "
                       f"{(rec or {}).get('code', pid)}")
        return {"ok": True}
    raise HTTPException(404, "Saved project not found")


# ------------------------------------------------ shared Access .accdb (Excel DB)
# Read AND write the shared _OdrivDB_*.accdb so tools share one
# database file. Reading is pure-Python; writing uses UCanAccess (Java).

@api.get("/accdb/status")
async def accdb_status():
    """Report whether .accdb read/write + the fast JDBC path are available."""
    from engine import accdb_bridge
    read_ok = False
    try:
        import access_parser  # noqa: F401
        read_ok = True
    except Exception:
        pass
    try:
        jdbc = accdb_bridge.ucanaccess_status()
    except Exception:
        jdbc = {"ready": False, "java": accdb_bridge.java_available(),
                "present": [], "missing": [], "dir": ""}
    return {"read_available": read_ok,
            "write_available": accdb_bridge.java_available(),
            "fast_read_ready": jdbc.get("ready"),
            "jdbc": jdbc,
            "write_note": ("Writing to .accdb needs a Java runtime; the driver "
                           "downloads automatically on first use.")}


@api.get("/accdb/jdbc-jar-dir")
async def accdb_jdbc_jar_dir():
    """Where to place the UCanAccess jars by hand if auto-download is blocked."""
    from engine import accdb_bridge
    return {"dir": accdb_bridge.ucanaccess_jar_dir(),
            "jars": ["ucanaccess-5.0.1.jar", "jackcess-4.0.1.jar",
                     "commons-lang3-3.8.1.jar", "commons-logging-1.2.jar",
                     "hsqldb-2.5.0.jar"]}


@api.post("/accdb/check-path")
async def accdb_check_path(payload: dict = Body(...)):
    """Validate a CFG-style path (folder or file) and report the .accdb files
    found. Reads the source layout: <folder>\\_OdrivDB.accdb (catalog) plus
    <folder>\\<year>\\_OdrivDB_1..4.accdb (event shards)."""
    from engine import accdb_bridge
    path = (payload or {}).get("path") or ""
    year = (payload or {}).get("year") or await _shared_accdb_year()
    files = accdb_bridge.resolve_db_files(path, year)
    p = path.strip().strip('"') if path else ""
    # report any year subfolders discovered so the UI can hint at them
    import glob as _glob
    years = []
    if p and os.path.isdir(p):
        for d in sorted(_glob.glob(os.path.join(p, "*"))):
            if os.path.isdir(d) and _glob.glob(os.path.join(d, "_OdrivDB_*.accdb")):
                years.append(os.path.basename(d))
    return {"path": path, "year": year,
            "is_folder": os.path.isdir(p) if p else False,
            "found": [os.path.basename(f) for f in files], "count": len(files),
            "year_folders": years, "ok": len(files) > 0}


@api.post("/accdb/projects")
async def accdb_list_projects(payload: dict = Body(...)):
    """List saved projects from a .accdb file OR the Excel folder layout
    (catalog + year shards)."""
    from engine import accdb_bridge
    path = (payload or {}).get("path")
    year = (payload or {}).get("year") or await _shared_accdb_year()
    if not path or not accdb_bridge.db_exists(path, year):
        raise HTTPException(
            400, f"No Access database found at: {path!r}. Point to the folder "
            f"that holds _OdrivDB.accdb (and its year subfolder of "
            f"_OdrivDB_1..4.accdb), and check the VPN / mapped drive.")
    try:
        rows = accdb_bridge.read_projects(path, year)
    except Exception as e:
        raise HTTPException(400, f"Could not read .accdb: {e}")
    # shape for the browser
    out = []
    for r in rows:
        out.append({
            "ID": r.get("ID"), "code": r.get("code"),
            "energy": r.get("energy"), "gears": r.get("gears"),
            "NbGear": r.get("NbGear"), "milestone": r.get("milestone"),
            "aera": r.get("aera"), "Mode": r.get("Mode"),
            "Version": r.get("Version"),
            "target_vehicle": r.get("target_vehicle"),
            "DateCreation": str(r.get("DateCreation") or ""),
            "Uniquename": r.get("Uniquename"),
            "db_file": os.path.basename(r.get("_db_file") or "")})
    return {"projects": out, "total": len(out), "path": path,
            "shards": [os.path.basename(f)
                       for f in accdb_bridge.resolve_db_files(path, year)]}


@api.post("/accdb/import")
async def accdb_import_project(payload: dict = Body(...)):
    """Import one project (+ its events) from a .accdb and open it as active.
    `path` may be a folder of _OdrivDB_*.accdb shards or a single file."""
    from engine import accdb_bridge
    path = (payload or {}).get("path")
    pid = (payload or {}).get("project_id")
    year = (payload or {}).get("year") or await _shared_accdb_year()
    if not path or not accdb_bridge.db_exists(path, year):
        raise HTTPException(400, f"No Access database found at: {path!r} "
                                 f"(check the VPN / mapped drive).")
    if pid is None:
        raise HTTPException(400, "project_id is required")
    projs = {str(p.get("ID")): p for p in accdb_bridge.read_projects(path, year)}
    rec = projs.get(str(pid))
    if not rec:
        raise HTTPException(404, f"Project ID {pid} not found in the database")
    # map Access projet columns -> our project fields
    project = {
        "name_code": rec.get("code"), "fuel": rec.get("energy"),
        "gearbox": rec.get("gears"), "gears": rec.get("gears"),
        "number_of_gears": str(rec.get("NbGear") or ""),
        "mode": rec.get("Mode"), "eval_mode": "Full",
        "software_milestone": rec.get("software") or rec.get("droopy"),
        "odriv_milestone": rec.get("software") or rec.get("droopy"),
        "priority": rec.get("priority"),
        "version": str(rec.get("Version") or "4.6").lstrip("Vv"),
        "area": rec.get("aera"), "target_vehicle": rec.get("target_vehicle"),
        "droopy": rec.get("droopy")}
    # read events (channel dicts keyed col_N) and map col_N -> acquisition headers
    cfg = await get_config()
    colnum_to_header = await _entete_colnum_map(cfg)
    raw_events = accdb_bridge.read_project_events(
        path, pid, db_file=rec.get("_db_file"), year=year)
    canon = canon_map_of(cfg)
    events = []
    for ev in raw_events:
        channels = {}
        for k, v in ev.items():
            if k == "sdv":
                continue
            try:
                cn = int(str(k).replace("col_", ""))
            except ValueError:
                continue
            header = colnum_to_header.get(cn)
            if header and v is not None:
                channels[header] = v
        # keep the SDV classification already stored in dataId
        stored = ev.get("sdv") or ""
        sdv = config_loader.canon_name(stored, canon) or stored
        events.append({"id": str(uuid.uuid4()), "sdv": sdv,
                       "channels": channels, "file": os.path.basename(path),
                       "imported_at": datetime.now(timezone.utc).isoformat()})
    await _erase_all()
    project["id"] = str(uuid.uuid4())
    project["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.project.insert_one(dict(project))
    if events:
        await db.events.insert_many([dict(e) for e in events])
    await moniteur(f"Imported project from Access DB : {rec.get('code')} "
                   f"({len(events)} events)")
    project.pop("_id", None)
    return {"ok": True, "project": project, "event_count": len(events)}


@api.post("/accdb/export")
async def accdb_export_project(payload: dict = Body(...)):
    """Write the current processed project INTO a shared .accdb (Excel schema)."""
    from engine import accdb_bridge
    from engine import projects_db
    path = (payload or {}).get("path")
    if not path:
        raise HTTPException(400, "path to the .accdb (or its folder) is required")
    _year = await _shared_accdb_year()
    if not accdb_bridge.db_exists(path, _year):
        raise HTTPException(400, f"No Access database found at: {path!r} "
                                 f"(check the VPN / mapped drive).")
    if not accdb_bridge.java_available():
        raise HTTPException(400, "Writing to .accdb requires a Java runtime "
                                 "(java) on this machine.")
    project = await get_project()
    if not project:
        raise HTTPException(400, "No project to export")
    glob = await db.rating_global.find_one({}, {"_id": 0})
    if not glob:
        raise HTTPException(400, "Calculate the rating before exporting.")
    events = await db.events.find({}, {"_id": 0}).to_list(100000)
    cfg = await get_config()
    m_idx = scoring.milestone_index(project, cfg["configurations"])
    uniquename = projects_db.build_uniquename(project, m_idx + 1,
                                              project.get("number_of_gears"))
    projet_row = {
        "DateCreation": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "code": project.get("name_code"),
        "droopy": project.get("software_milestone"),
        "gears": project.get("gears") or project.get("gearbox"),
        "energy": (project.get("fuel") or "").upper(),
        "priority": project.get("priority"),
        "milestone": m_idx + 1, "aera": project.get("area"),
        "target": project.get("priority"),
        "software": project.get("software_milestone"),
        "target_vehicle": project.get("target_vehicle"),
        "Version": "V" + str(project.get("version") or "4.6").lstrip("Vv"),
        "Mode": project.get("mode") or "AUTO", "Uniquename": uniquename,
        "NbGear": project.get("number_of_gears"), "ColonneDb": None}
    header_to_colnum = {h: n for n, h in
                        (await _entete_colnum_map(cfg)).items()}
    ev_payload = [dict({"sdv": e.get("sdv")}, **(e.get("channels") or {}))
                  for e in events]
    try:
        new_id, shard = accdb_bridge.write_project(
            path, projet_row, ev_payload, header_to_colnum, year=_year)
    except Exception as e:
        raise HTTPException(400, f"Write to .accdb failed: {e}")
    await moniteur(f"Exported project to Access DB : {projet_row['code']} "
                   f"(ID {new_id}, {len(ev_payload)} events, "
                   f"{os.path.basename(shard)})")
    return {"ok": True, "project_id": new_id, "event_count": len(ev_payload),
            "uniquename": uniquename, "shard": os.path.basename(shard)}


def _build_colnum_header_map(cfg):
    """Best-effort col_N <-> acquisition-header map from the structure config's
    import column order (col_1..col_742 follow the acquisition column order)."""
    headers = []
    struct = cfg.get("structure") or {}
    seen = set()
    for sdv, blocks in (struct.items() if isinstance(struct, dict) else []):
        for cat in ("columns", "data", "criteria"):
            for item in (blocks.get(cat) or []):
                name = item.get("import") or item.get("name") if isinstance(item, dict) else None
                if name and name not in seen:
                    seen.add(name)
                    headers.append(name)
    return {i + 1: h for i, h in enumerate(headers)}


async def _entete_colnum_map(cfg):
    """col_N -> channel-name using the authoritative `entete` layout. Prefers the
    SQLite database's baked-in entete, then the shared .accdb catalog's entete,
    then a structure-based guess as a last resort."""
    from engine import accdb_bridge, sqlite_bridge
    path = await _shared_accdb_path()
    year = await _shared_accdb_year()
    # 1) SQLite (self-contained, fast)
    if sqlite_bridge.db_exists(path):
        try:
            em = sqlite_bridge.read_entete_colmap(path)
            if em:
                return {cn: info["name"] for cn, info in em.items()
                        if info.get("name")}
        except Exception:
            pass
    # 2) shared .accdb catalog
    if path and accdb_bridge.db_exists(path, year):
        try:
            em = accdb_bridge.read_entete_colmap(path, year)
            if em:
                # map col number -> the channel name the engine resolves
                return {cn: info["name"] for cn, info in em.items()
                        if info.get("name")}
        except Exception:
            pass
    # 3) structure-based fallback
    return _build_colnum_header_map(cfg)


# ------------------------------------------------ app settings (shared DB path)
# Configuration for the .accdb path on the shared drive, which is
# stored once. Persisted in the same store, so it survives restarts.

@api.get("/settings")
async def get_settings():
    doc = await db.app_settings.find_one({"_id_key": "app"}, {"_id": 0})
    return doc or {"_id_key": "app", "accdb_path": ""}


@api.put("/settings")
async def update_settings(payload: dict = Body(...)):
    allowed = {k: v for k, v in (payload or {}).items()
               if k in ("accdb_path", "accdb_year")}
    await db.app_settings.update_one(
        {"_id_key": "app"}, {"$set": {**allowed, "_id_key": "app"}}, upsert=True)
    if "accdb_path" in allowed:
        await moniteur(f"Shared database path set : {allowed['accdb_path']}")
        # If this points to a SQLite database, pre-warm the target cache in the
        # background so the first selection of each vehicle is already scored
        # (the slow part happens once, proactively, not while the user waits).
        try:
            import asyncio
            from engine import sqlite_bridge
            if sqlite_bridge.db_exists(allowed["accdb_path"]):
                asyncio.create_task(_prewarm_sqlite_cache(allowed["accdb_path"]))
        except Exception:
            pass
    if "accdb_year" in allowed:
        await moniteur(f"Shared database year set : {allowed['accdb_year']}")
    return await get_settings()


_PREWARM_STATE = {"running": False, "done": 0, "total": 0}


async def _prewarm_sqlite_cache(path):
    """Background task: score every SQLite vehicle once so its result is cached.
    Skips vehicles already cached. Safe to run repeatedly."""
    import asyncio
    from engine import sqlite_bridge
    if _PREWARM_STATE["running"]:
        return
    _PREWARM_STATE["running"] = True
    try:
        projs = await asyncio.to_thread(sqlite_bridge.read_projects, path)
        _PREWARM_STATE["total"] = len(projs)
        _PREWARM_STATE["done"] = 0
        for p in projs:
            code = p.get("code")
            if not code:
                _PREWARM_STATE["done"] += 1
                continue
            ident = {"id": p.get("ID"), "code": code,
                     "uniquename": p.get("Uniquename"), "db_file": ""}
            # skip if already cached
            sf = sqlite_bridge.find_sqlite(path)
            cache_id = code
            if _accdb_result_cache_get(sf, None, cache_id) is None:
                try:
                    await _resolve_target_rows("sqlite", ident)
                except Exception:
                    pass
            _PREWARM_STATE["done"] += 1
        await moniteur(f"Target cache pre-warmed: {_PREWARM_STATE['done']} "
                       f"vehicles ready for instant comparison.")
    finally:
        _PREWARM_STATE["running"] = False


@api.get("/targets/prewarm-status")
async def prewarm_status():
    return dict(_PREWARM_STATE)


async def _shared_accdb_path():
    s = await db.app_settings.find_one({"_id_key": "app"}, {"_id": 0})
    return (s or {}).get("accdb_path") or ""


async def _shared_accdb_year():
    s = await db.app_settings.find_one({"_id_key": "app"}, {"_id": 0})
    return (s or {}).get("accdb_year") or None


# ------------------------------------------------ saved projects as TARGETS
# A saved project (from the shared .accdb or the tool DB) can be selected as the
# comparison TARGET in New Project, exactly like the Excel target dropdown.

@api.get("/targets/available")
async def targets_available():
    """All selectable comparison targets: the static reference vehicles plus the
    saved projects from the tool DB and (if configured) the shared .accdb."""
    cfg_conf = await get_config("configurations")
    refs = cfg_conf.get("target_vehicles") or []
    # tool-DB saved projects
    tool = await db.projets.find(
        {}, {"_id": 0, "id": 1, "code": 1, "Uniquename": 1,
             "driv_index": 1, "dyn_index": 1}).to_list(1000)
    tool_targets = [{"label": p["code"], "source": "tool",
                     "id": p["id"], "uniquename": p.get("Uniquename")}
                    for p in tool]
    # shared .accdb saved projects (path may be a folder of shards)
    accdb_targets = []
    accdb_error = None
    path = await _shared_accdb_path()
    _year = await _shared_accdb_year()
    from engine import accdb_bridge
    from engine import sqlite_bridge
    # Prefer the converted SQLite database when one is present at/near the
    # configured path: it is local and indexed, so reading + scoring targets is
    # far faster than the network .accdb. Falls back to .accdb otherwise.
    sqlite_file = sqlite_bridge.find_sqlite(path)
    if sqlite_file:
        try:
            for p in sqlite_bridge.read_projects(path):
                code = p.get("code")
                if code is None or str(code).strip() == "":
                    continue
                accdb_targets.append({
                    "label": str(code), "source": "sqlite",
                    "id": p.get("ID"),
                    "uniquename": p.get("Uniquename"),
                    "db_file": os.path.basename(sqlite_file)})
            if not accdb_targets:
                accdb_error = ("The SQLite database was read but contains no "
                               "vehicles.")
        except Exception as e:
            accdb_error = f"Could not read the SQLite database: {e}"
        return {"references": refs, "tool": tool_targets,
                "accdb": accdb_targets, "accdb_error": accdb_error,
                "accdb_path": sqlite_file}
    if path:
        if not accdb_bridge.db_exists(path, _year):
            accdb_error = (f"No _OdrivDB.accdb found at {path!r} "
                           f"(year={_year}). Check the path and that the VPN / "
                           f"mapped drive is connected.")
        else:
            try:
                rows = accdb_bridge.read_projects(path, _year)
                for p in rows:
                    code = p.get("code")
                    if code is None or str(code).strip() == "":
                        continue                 # skip rows with no name
                    accdb_targets.append({
                        "label": str(code), "source": "accdb",
                        "id": p.get("ID"),
                        "uniquename": p.get("Uniquename"),
                        "db_file": os.path.basename(p.get("_db_file") or "")})
                if not accdb_targets:
                    accdb_error = ("The shared database was read but returned no "
                                   "projects (the projet table may be empty or in "
                                   "an unexpected format).")
            except Exception as e:
                accdb_error = f"Could not read the shared database: {e}"
    return {"references": refs, "tool": tool_targets, "accdb": accdb_targets,
            "accdb_error": accdb_error,
            "accdb_path": path}


def _accdb_result_cache_dir():
    import os
    d = os.path.join(os.path.expanduser("~"), ".odriv", "targetcache")
    os.makedirs(d, exist_ok=True)
    return d


def _accdb_result_cache_key(path, year, ident):
    """Key the cache by project id + the resolved DB file's mtime+size, so it
    auto-invalidates whenever the underlying database changes. Works for both
    the .accdb shards and the SQLite database."""
    import os, hashlib
    from engine import accdb_bridge, sqlite_bridge
    # bump this when the cached row shape or key scheme changes
    #   v2: added _global_driv/_global_dyn
    #   v3: added _rate_low_driv/_rate_low_dyn (weighted % below target)
    #   v4: key by unique vehicle code (not ID) to fix ID-collision
    #   v5: include the SQLite file signature so the cache is correct for it too
    sig = ["v5", str(ident), str(year)]
    files = []
    # SQLite database (if the path resolves to one)
    sf = sqlite_bridge.find_sqlite(path)
    if sf:
        files.append(sf)
    else:
        try:
            files.extend(accdb_bridge.resolve_db_files(path, year))
        except Exception:
            pass
    for f in files:
        try:
            sig.append("%s:%d:%d" % (os.path.basename(f),
                                     int(os.path.getmtime(f)),
                                     os.path.getsize(f)))
        except OSError:
            pass
    return hashlib.md5("|".join(sig).encode()).hexdigest()


def _accdb_result_cache_get(path, year, ident):
    import os, json
    fp = os.path.join(_accdb_result_cache_dir(),
                      _accdb_result_cache_key(path, year, ident) + ".json")
    try:
        if os.path.exists(fp):
            with open(fp, "r") as fh:
                return json.load(fh)
    except Exception:
        pass
    return None


def _accdb_result_cache_put(path, year, ident, vehicle, rows):
    import os, json
    fp = os.path.join(_accdb_result_cache_dir(),
                      _accdb_result_cache_key(path, year, ident) + ".json")
    try:
        with open(fp, "w") as fh:
            json.dump({"vehicle": vehicle, "rows": rows}, fh)
    except Exception:
        pass


async def _resolve_target_rows(source, ident):
    """Resolve one target into its per-SDV index rows. Returns
    (vehicle_label, rows) or raises HTTPException. Sources:
      - "ref"  : a built-in reference benchmark (config target dataset). Its
                 per-SDV "index" is the benchmark target index the engine uses.
      - "tool" : a saved project in the tool database.
      - "accdb": a saved project in the shared Access DB.
    """
    if source == "ref":
        # A reference vehicle has pre-stored per-SDV target indices in the seed
        # target_vehicle data (target_vehicle.json), keyed by vehicle name. Pull
        # that vehicle's rows so it shows as a comparison column + marker.
        label = ident if isinstance(ident, str) else str(ident or "Reference")
        seed = config_loader.load_seed_sections()
        seed = ({s["key"]: s["data"] for s in seed}
                if isinstance(seed, list) else seed)
        all_rows = ((seed.get("target_vehicle") or {}).get("rows")) or []
        rows = [{"sdv": r["sdv"],
                 "driv": r.get("driv"), "dyn": r.get("dyn"),
                 "vehicle": label,
                 "drive_version": r.get("drive_version") or "V4.6",
                 "mode": r.get("mode") or "AUTO"}
                for r in all_rows
                if str(r.get("vehicle", "")).strip() == label.strip()]
        if not rows:
            raise HTTPException(
                422, f"Reference '{label}' has no stored per-SDV target indices.")
        # compute this reference's global driv/dyn index as the engine does:
        # a weighted average of per-SDV indices using each SDV's block weight.
        try:
            cfg = await get_config()
            blocks = cfg.get("settings_blocks") or {}
            wmap = {k.strip().upper(): (v.get("weight") or 10)
                    for k, v in blocks.items()}
            for part in ("driv", "dyn"):
                num = den = 0.0
                for r in rows:
                    v = r.get(part)
                    if v is None:
                        continue
                    w = wmap.get(str(r["sdv"]).strip().upper(), 10)
                    num += v * w
                    den += w
                rows[0][f"_global_{part}"] = round(num / den, 1) if den else None
        except Exception:
            pass
        return label, rows
    if source == "tool":
        rec = await db.projets.find_one({"id": ident}, {"_id": 0})
        if not rec:
            raise HTTPException(404, "Saved project not found")
        sdv_rows = rec.get("_sdv_results") or []
        rows = [{"sdv": r["name"],
                 "driv": (r.get("driv") or {}).get("index"),
                 "dyn": (r.get("dyn") or {}).get("index"),
                 "vehicle": rec.get("code"),
                 "drive_version": rec.get("Version") or "V4.6",
                 "mode": rec.get("Mode") or "AUTO"}
                for r in sdv_rows]
        # attach the saved project's global driv/dyn index for the graph marker
        if rows:
            g = rec.get("_global") or {}
            rows[0]["_global_driv"] = (g.get("driv") or {}).get("index")
            rows[0]["_global_dyn"] = (g.get("dyn") or {}).get("index")
            rows[0]["_rate_low_driv"] = (g.get("driv") or {}).get("rate_low")
            rows[0]["_rate_low_dyn"] = (g.get("dyn") or {}).get("rate_low")
        return rec.get("code"), rows
    elif source == "sqlite":
        # Fast path: read the vehicle's events from the local indexed SQLite and
        # score them. Same scoring as .accdb, but the read is a single indexed
        # query (a few ms) instead of parsing network Access tables.
        import asyncio
        path = await _shared_accdb_path()
        from engine import sqlite_bridge
        sqlite_file = sqlite_bridge.find_sqlite(path)
        if not sqlite_file:
            raise HTTPException(400, "SQLite database not found at the configured "
                                     "path.")
        if isinstance(ident, dict):
            want_code = ident.get("code")
            want_id = ident.get("id")
            cache_id = want_code or want_id
        else:
            want_code = ident if isinstance(ident, str) else None
            want_id = ident
            cache_id = ident
        # scored-result cache (keyed by unique code + db mtime), same as accdb
        cached = _accdb_result_cache_get(sqlite_file, None, cache_id)
        if cached is not None:
            return cached["vehicle"], cached["rows"]

        projs = await asyncio.to_thread(sqlite_bridge.read_projects, path)
        rec = None
        if want_code is not None:
            rec = next((p for p in projs
                        if str(p.get("code")) == str(want_code)), None)
        if rec is None and want_id is not None:
            rec = next((p for p in projs
                        if str(p.get("ID")) == str(want_id)), None)
        if not rec:
            raise HTTPException(404, "Vehicle not found in SQLite database")
        cfg = await get_config()
        colnum_to_header = await _entete_colnum_map(cfg)
        canon = canon_map_of(cfg)
        # read + score this vehicle's events
        raw = await asyncio.to_thread(
            sqlite_bridge.read_project_events, path, rec.get("code"))
        events = []
        for ev in raw:
            # the SQLite event stores raw col_N keys; translate each to its
            # channel name via the column-header map, exactly like the .accdb
            # path, so the scorer recognises the channels.
            channels = {}
            for k, v in ev.items():
                if k == "sdv" or v is None:
                    continue
                try:
                    cn = int(str(k).replace("col_", ""))
                except ValueError:
                    continue
                h = colnum_to_header.get(cn)
                if h:
                    channels[h] = v
            stored = ev.get("sdv") or ""
            sdv = config_loader.canon_name(stored, canon) or stored
            if sdv:
                events.append({"id": str(uuid.uuid4()), "sdv": sdv,
                               "channels": channels})
        tproj = {"name_code": rec.get("code"), "fuel": rec.get("energy"),
                 "gearbox": rec.get("gears"), "gears": rec.get("gears"),
                 "number_of_gears": str(rec.get("NbGear") or ""),
                 "mode": rec.get("Mode"), "eval_mode": "Full",
                 "software_milestone": rec.get("software") or rec.get("droopy"),
                 "odriv_milestone": rec.get("software") or rec.get("droopy"),
                 "priority": rec.get("priority"),
                 "version": str(rec.get("Version") or "4.6").lstrip("Vv"),
                 "area": rec.get("aera"),
                 "target_vehicle": rec.get("target_vehicle")}
        tl = config_loader.build_targets_lookup(cfg["targets"], tproj)
        _, sdv_results, tglobal = scoring.calculate_rating(
            tproj, events, cfg, tl, canon)
        rows = [{"sdv": r["name"],
                 "driv": (r.get("driv") or {}).get("index"),
                 "dyn": (r.get("dyn") or {}).get("index"),
                 "vehicle": rec.get("code"),
                 "drive_version": rec.get("Version") or "V4.6",
                 "mode": rec.get("Mode") or "AUTO"}
                for r in sdv_results if r.get("driv")]
        if not rows:
            raise HTTPException(
                422, "This vehicle's events could not be scored from the SQLite "
                "database (its channel layout isn't recognised).")
        rows[0]["_global_driv"] = (tglobal.get("driv") or {}).get("index")
        rows[0]["_global_dyn"] = (tglobal.get("dyn") or {}).get("index")
        rows[0]["_rate_low_driv"] = (tglobal.get("driv") or {}).get("rate_low")
        rows[0]["_rate_low_dyn"] = (tglobal.get("dyn") or {}).get("rate_low")
        _accdb_result_cache_put(sqlite_file, None, cache_id, rec.get("code"), rows)
        return rec.get("code"), rows
    elif source == "accdb":
        import asyncio
        path = await _shared_accdb_path()
        _year = await _shared_accdb_year()
        from engine import accdb_bridge
        if not path or not accdb_bridge.db_exists(path, _year):
            raise HTTPException(400, "Shared database path not set or the drive "
                                     "is unavailable (check the VPN).")
        # SCORED-RESULT CACHE: scoring an .accdb comparison vehicle requires
        # reading + re-scoring its events, which is slow on a network drive. The
        # *result* (per-SDV indices) is tiny and doesn't change unless the .accdb
        # changes, so cache it on disk keyed by project id + DB mtime. Repeat
        # comparisons against the same vehicle are then instant (no file read).
        # ident may be a composite dict {id, code, uniquename, db_file} (new) or
        # a bare id/string (legacy). Resolve the unique vehicle code from it.
        if isinstance(ident, dict):
            want_code = ident.get("code")
            want_id = ident.get("id")
            want_uniq = ident.get("uniquename")
            cache_id = want_code or want_uniq or want_id
        else:
            want_code = None
            want_id = ident
            want_uniq = None
            cache_id = ident
        cached = _accdb_result_cache_get(path, _year, cache_id)
        if cached is not None:
            return cached["vehicle"], cached["rows"]

        all_projs = await asyncio.to_thread(accdb_bridge.read_projects, path, _year)
        rec = None
        # Prefer matching by unique code (the vehicle name shown as the column
        # header); fall back to uniquename, then ID. This prevents two vehicles
        # that share an ID (or have a null ID) from collapsing to the same row.
        if want_code is not None:
            rec = next((p for p in all_projs
                        if str(p.get("code")) == str(want_code)), None)
        if rec is None and want_uniq is not None:
            rec = next((p for p in all_projs
                        if str(p.get("Uniquename")) == str(want_uniq)), None)
        if rec is None and want_id is not None:
            rec = next((p for p in all_projs
                        if str(p.get("ID")) == str(want_id)), None)
        if not rec:
            raise HTTPException(404, "Project not found in shared database")
        cfg = await get_config()
        colnum_to_header = await _entete_colnum_map(cfg)
        raw = await asyncio.to_thread(
            accdb_bridge.read_project_events, path, ident,
            rec.get("_db_file"), _year)
        canon = canon_map_of(cfg)
        events = []
        for ev in raw:
            channels = {}
            for k, v in ev.items():
                if k == "sdv" or v is None:
                    continue
                try:
                    cn = int(str(k).replace("col_", ""))
                except ValueError:
                    continue
                h = colnum_to_header.get(cn)
                if h:
                    channels[h] = v
            stored = ev.get("sdv") or ""
            sdv = config_loader.canon_name(stored, canon) or stored
            if sdv:
                events.append({"id": str(uuid.uuid4()), "sdv": sdv,
                               "channels": channels})
        tproj = {"name_code": rec.get("code"), "fuel": rec.get("energy"),
                 "gearbox": rec.get("gears"), "gears": rec.get("gears"),
                 "number_of_gears": str(rec.get("NbGear") or ""),
                 "mode": rec.get("Mode"), "eval_mode": "Full",
                 "software_milestone": rec.get("software") or rec.get("droopy"),
                 "odriv_milestone": rec.get("software") or rec.get("droopy"),
                 "priority": rec.get("priority"),
                 "version": str(rec.get("Version") or "4.6").lstrip("Vv"),
                 "area": rec.get("aera"),
                 "target_vehicle": rec.get("target_vehicle")}
        tl = config_loader.build_targets_lookup(cfg["targets"], tproj)
        _, sdv_results, tglobal = scoring.calculate_rating(
            tproj, events, cfg, tl, canon)
        rows = [{"sdv": r["name"],
                 "driv": (r.get("driv") or {}).get("index"),
                 "dyn": (r.get("dyn") or {}).get("index"),
                 "vehicle": rec.get("code"),
                 "drive_version": rec.get("Version") or "V4.6",
                 "mode": rec.get("Mode") or "AUTO"}
                for r in sdv_results if r.get("driv")]
        if not rows:
            raise HTTPException(
                422, "This project's events could not be scored from the shared "
                ".accdb (its channel-column layout isn't recognised). Import it "
                "via SAVED PROJECTS \u2192 Shared Access DB, then Calculate and "
                "Save to the tool database; you can then select it as a target.")
        # stash the target's own global driv/dyn index on the first row so the
        # RATING graph can place this vehicle's marker on the index bar.
        if rows:
            rows[0]["_global_driv"] = (tglobal.get("driv") or {}).get("index")
            rows[0]["_global_dyn"] = (tglobal.get("dyn") or {}).get("index")
            rows[0]["_rate_low_driv"] = (tglobal.get("driv") or {}).get("rate_low")
            rows[0]["_rate_low_dyn"] = (tglobal.get("dyn") or {}).get("rate_low")
        _accdb_result_cache_put(path, _year, cache_id, rec.get("code"), rows)
        return rec.get("code"), rows
    else:
        raise HTTPException(400, "source must be 'tool' or 'accdb'")


@api.post("/targets/apply")
async def targets_apply(payload: dict = Body(...)):
    """Load a saved project's per-SDV indices into the TARGET VEHICLE column so
    the current project is scored against it (the comparison benchmark)."""
    source = (payload or {}).get("source")        # tool | accdb
    ident = (payload or {}).get("id")
    vehicle, rows = await _resolve_target_rows(source, ident)
    # write into target_vehicle config so RATING shows it as the comparison col
    tv = await get_config("target_vehicle")
    existing = {r["sdv"].strip().upper(): r for r in tv["rows"]}
    for row in rows:
        existing[row["sdv"].strip().upper()] = row
    tv["rows"] = list(existing.values())
    tv["targets"] = [vehicle]                      # single-target mode
    await db.config.update_one({"section": "target_vehicle"},
                               {"$set": {"data": tv}})
    proj = await get_project()
    if proj:
        await db.project.update_one({"id": proj["id"]},
                                    {"$set": {"target_vehicle": vehicle,
                                              "target_vehicles": [vehicle]}})
    await moniteur(f"Comparison target set to saved project : {vehicle}")
    return {"ok": True, "vehicle": vehicle, "rows": len(rows)}


@api.post("/targets/apply-multi")
async def targets_apply_multi(payload: dict = Body(...)):
    """Apply MULTIPLE comparison targets at once. Each target's per-SDV indices
    are stored side by side (keyed by SDV + vehicle), so the RATING sheet can
    show one comparison column per selected vehicle."""
    targets = (payload or {}).get("targets") or []   # [{source,id,label}, ...]
    if not targets:
        raise HTTPException(400, "No targets provided")
    tv = await get_config("target_vehicle")
    # multi rows live in a separate structure keyed by vehicle so they don't
    # collide; the legacy single 'rows' is also kept (first target) for back-compat
    multi = {}                                       # vehicle -> {SDV: row}
    labels = []
    errors = []
    for t in targets:
        try:
            vehicle, rows = await _resolve_target_rows(t.get("source"), t.get("id"))
        except HTTPException as e:
            errors.append({"target": t.get("label"), "detail": e.detail})
            continue
        labels.append(vehicle)
        multi[vehicle] = {r["sdv"].strip().upper(): r for r in rows}
    if not multi:
        raise HTTPException(422, {"message": "None of the targets could be applied",
                                  "errors": errors})
    # store: per-vehicle SDV rows + the flat list for the first vehicle (legacy)
    tv["multi"] = {veh: list(rowmap.values()) for veh, rowmap in multi.items()}
    tv["targets"] = labels
    first_rows = list(next(iter(multi.values())).values())
    existing = {r["sdv"].strip().upper(): r for r in tv.get("rows", [])}
    for row in first_rows:
        existing[row["sdv"].strip().upper()] = row
    tv["rows"] = list(existing.values())
    await db.config.update_one({"section": "target_vehicle"},
                               {"$set": {"data": tv}})
    proj = await get_project()
    if proj:
        await db.project.update_one(
            {"id": proj["id"]},
            {"$set": {"target_vehicle": labels[0], "target_vehicles": labels}})
    await moniteur(f"Comparison targets set ({len(labels)}): {', '.join(labels)}")
    return {"ok": True, "vehicles": labels, "applied": len(labels),
            "errors": errors}


@api.post("/targets/pending")
async def targets_set_pending(payload: dict = Body(...)):
    """Record which target vehicle(s) the project should be scored against,
    WITHOUT reading their events. Instant. The actual (slow) read + re-score of
    these target vehicles is deferred to the "Set as target" button on RATING.

    payload: {primary:{source,id,label}|null, extras:[{source,id,label}, ...]}
    A target is kept if it has an id (tool/accdb) OR a label (reference vehicle).
    """
    primary = (payload or {}).get("primary")
    extras = (payload or {}).get("extras") or []
    pend = []

    def _keep(t):
        if not t:
            return
        if t.get("id") is not None or t.get("label"):
            pend.append({"source": t.get("source"), "id": t.get("id"),
                         "label": t.get("label")})
    _keep(primary)
    for e in extras:
        _keep(e)
    tv = await get_config("target_vehicle")
    tv["pending"] = pend                # resolved on "Set as target"
    # clear any previously-resolved target data so columns/graph stay empty
    # until the user presses "Set as target"
    tv["multi"] = {}
    tv["targets"] = []
    tv["rows"] = []
    await db.config.update_one({"section": "target_vehicle"},
                               {"$set": {"data": tv}})
    if pend:
        await moniteur(f"Target vehicle(s) selected ({len(pend)}); press "
                       f"'Set as target' on RATING to score them.")
    return {"ok": True, "pending": len(pend),
            "labels": [p.get("label") for p in pend]}


async def _resolve_pending_targets():
    """Resolve any pending comparison targets (set by New Project) into per-SDV
    rows. Called from calculate_rating so the slow .accdb read happens during
    Calculate, not when the dialog is open. Stores results into target_vehicle
    config exactly like apply-multi does."""
    tv = await get_config("target_vehicle")
    pend = (tv or {}).get("pending") or []
    if not pend:
        return
    multi = {}
    labels = []
    primary_rows = None
    for i, t in enumerate(pend):
        try:
            vehicle, rows = await _resolve_target_rows(t.get("source"), t.get("id"))
        except Exception:
            continue
        labels.append(vehicle)
        multi[vehicle] = {r["sdv"].strip().upper(): r for r in rows}
        if i == 0:
            primary_rows = rows
    if not multi:
        return
    tv["multi"] = {veh: list(rowmap.values()) for veh, rowmap in multi.items()}
    tv["targets"] = labels
    # per-SDV target column reads from rows -> use the primary target's values
    if primary_rows is not None:
        tv["rows"] = [dict(r) for r in primary_rows]
    await db.config.update_one({"section": "target_vehicle"},
                               {"$set": {"data": tv}})


# --------------------------------------------------------------- SDV sheet detail

@api.get("/sdv/{name}")
async def sdv_detail(name: str):
    project = await get_project()
    cfg = await get_config()
    canon = canon_map_of(cfg)
    cname = config_loader.canon_name(name, canon)
    events = await db.events.find({"sdv": cname}, {"_id": 0}).to_list(10000)
    if not events:
        raise HTTPException(404, f"No events for SDV {name}")
    result = await db.sdv_results.find_one({"name": cname}, {"_id": 0})
    spec = cfg["structure"].get(cname, {"columns": [], "data": [], "criteria": []})
    targets_lookup = config_loader.build_targets_lookup(cfg["targets"], project or {})
    targets = targets_lookup.get(cname.strip().upper(), {})
    charts = {k.strip().upper(): v for k, v in cfg["chart_params"].items()}.get(
        cname.strip().upper(), [])
    # Ensure an Acceleration vs Speed chart exists for every SDV (added view).
    chart_axes = [(c.get("x"), c.get("y")) for c in charts]
    if ("Vehicle Speed", "AccelerationChassis") not in chart_axes:
        charts = list(charts) + [{
            "name": "Acceleration vs Speed", "active": False,
            "x": "Vehicle Speed", "y": "AccelerationChassis",
            "x_min": 0, "x_max": 140, "x_step": 10,
            "y_min": -5, "y_max": 5, "y_step": 1, "added": True}]
    # flatten event rows for the sheet grid, with server-resolved chart points
    # (uses the alias-aware get_channel so axes like "Throttle Position"->pedal
    # and "AccelerationChassis"->ax resolve even when the raw column differs).
    from engine.classifier import get_channel as _gc, MISSING as _MISSING, _norm as _normch
    # Chart axes that should use the physical signal rather than the scoring
    # alias. AccelerationChassis on the chart means actual longitudinal accel
    # ("ax level" m/s2), not the agreement-rating column the scorer may pick.
    _CHART_AXIS_PREF = {"accelerationchassis": ["ax level", "ax mean"]}
    def _num(ch, axis):
        pref = _CHART_AXIS_PREF.get(_normch(axis))
        if pref:
            for want in pref:
                for key, val in ch.items():
                    k = _normch(key)
                    kc = k.split(",", 1)[1].strip() if "," in k else k
                    if kc == want:
                        try:
                            return float(val)
                        except (TypeError, ValueError):
                            pass
        v = _gc(ch, axis)
        if v is _MISSING or v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    axis_names = sorted({a for c in charts for a in (c.get("x"), c.get("y")) if a})
    rows = []
    for ev in events:
        ch = ev["channels"]
        row = {"id": ev["id"], "file": ev.get("file"),
               "driv": ev.get("driv"), "dyn": ev.get("dyn"), "channels": ch,
               "axis": {a: _num(ch, a) for a in axis_names}}
        rows.append(row)

    # ---- Drivability/Responsiveness SUMMARY panel (per-SDV) ----
    # Reproduces the Excel SDV-tab summary: per-priority breakpoint counts +
    # green/yellow/red %s and the coverage rates
    # (G20/G21/G22 = events of priority p / number of breakpoint cells of p).
    summary = _sdv_summary(project, cname, events, cfg, targets_lookup)

    return {"name": cname, "result": result, "structure": spec,
            "targets": {k: {"wl": v.get("wl"), "t": v.get("t"),
                            "driv": v.get("driv"), "resp": v.get("resp")}
                        for k, v in targets.items()},
            "charts": charts, "events": rows, "project": project,
            "summary": summary}


def _sdv_summary(project, cname, events, cfg, targets_lookup):
    """Build the per-SDV Drivability/Responsiveness summary panel data for both
    parts. Returns {driv:{...}, dyn:{...}} where each holds:
      index, target_index, table (color x priority: events/breakpoints/pct/target),
      coverage (P1/P2/P3 fraction + overall), gauges (per-priority green%).
    """
    from engine import scoring as _sc
    from engine import dots as _dots
    sg = cfg["settings_global"]
    coefficients = sg["coefficients"]
    puiss = sg["constants"]["PUISS"]
    calculs = cfg["calculs"]
    grade = (project.get("priority") if project else "PREMIUM") or "PREMIUM"
    grade = grade.strip().upper()
    coef_orange = (calculs["coef_orange_mainstream"] if grade == "MAINSTREAM"
                   else calculs["coef_orange_premium"])
    coef_yellow = 1.0 / coef_orange
    facteur_redplus = calculs.get("facteur_redplus") or 2
    up = cname.strip().upper()
    criteria_rows = targets_lookup.get(up, {})
    prior_up = {k.strip().upper(): v for k, v in cfg["priorisation"].items()}
    all_cfgs = prior_up.get(up, [])
    prior_cfgs = _sc._gate_configs(all_cfgs, project or {})

    # K-column targets (verified from the reference dataset):
    #   GREEN P1/P2/P3 = 90/70/50 ; YELLOW = 10/20/30 ; RED = 0/10/20
    K_GREEN = {1: 90, 2: 70, 3: 50}
    K_YELLOW = {1: 10, 2: 20, 3: 30}
    K_RED = {1: 0, 2: 10, 3: 20}

    out = {}
    for part in ("driv", "dyn"):
        scores = []
        for ev in events:
            sc = _sc.score_event(ev["channels"], criteria_rows, part,
                                 coefficients, prior_cfgs, cfg["criticity"])
            if sc is not None:
                scores.append(sc)
        if not scores:
            out[part] = None
            continue
        idx = _sc.sdv_index(scores, puiss)
        # raw EVENT counts per color (the "Events" column G)
        ev_total = len(scores)
        ev_color = {"GREEN": 0, "YELLOW": 0, "RED": 0}
        for s in scores:
            c = s["color"].upper()
            if c == "RED +":
                c = "RED"
            if c in ev_color:
                ev_color[c] += 1
        # BREAKPOINT (operating-cell) counts + percentages (I and J columns)
        bp = _dots.count_breakpoints(scores)
        pj = _dots.summary_percentages(bp)
        # per-priority breakpoint totals across colors -> "Breakpoints" I8/9/10
        # green/yellow/red breakpoint counts -> I11.. via pj
        table = {
            "events": {"green": ev_color["GREEN"], "yellow": ev_color["YELLOW"],
                       "red": ev_color["RED"], "total": ev_total},
            "pct_of_total": {
                "green": round(100.0 * ev_color["GREEN"] / ev_total, 1) if ev_total else 0,
                "yellow": round(100.0 * ev_color["YELLOW"] / ev_total, 1) if ev_total else 0,
                "red": round(100.0 * ev_color["RED"] / ev_total, 1) if ev_total else 0},
            "breakpoints": {p: {"total": bp[p]["total"], "green": bp[p]["green"],
                                "yellow": bp[p]["yellow"], "red": bp[p]["red"]}
                            for p in (1, 2, 3)},
            "pct_total_prio": {p: round(pj_share(bp, p), 1) for p in (1, 2, 3)},
            "pct_green": {p: round(pj[p]["green_pct"], 1) for p in (1, 2, 3)},
            "pct_yellow": {p: round(pj[p]["yellow_pct"], 1) for p in (1, 2, 3)},
            "pct_red": {p: round(pj[p]["red_pct"], 1) for p in (1, 2, 3)},
            "target_green": K_GREEN, "target_yellow": K_YELLOW, "target_red": K_RED,
        }
        # coverage rate: events of priority p / number of breakpoint cells of p
        cov = {}
        for p in (1, 2, 3):
            ncells = bp[p]["total"]
            nev = sum(1 for s in scores if s.get("priority") == p)
            cov[p] = round(nev / ncells, 4) if ncells else 0.0
        # overall coverage = weighted by each priority's breakpoint-cell count
        # (priorities with no operating cells don't dilute the result), matching
        # the single combined % Excel shows next to P1/P2/P3.
        tot_cells = sum(bp[p]["total"] for p in (1, 2, 3))
        cov_overall = (round(sum(min(cov[p], 1.0) * bp[p]["total"]
                                 for p in (1, 2, 3)) / tot_cells, 4)
                       if tot_cells else 0.0)
        out[part] = {
            "index": idx,
            "target_index": (targets_lookup.get(up, {}) and None),
            "table": table,
            "coverage": cov,
            "coverage_overall": cov_overall,
            # gauges show the per-priority GREEN% (the donut fill) against the
            # K-target green threshold
            "gauges": {p: {"green_pct": round(pj[p]["green_pct"], 1),
                           "target": K_GREEN[p],
                           "n_total": bp[p]["total"]} for p in (1, 2, 3)},
        }
    # attach per-SDV target index from the seed reference vehicle rows. Excel
    # always shows a Target Index for the SDV (the benchmark), independent of any
    # comparison vehicle the user selects. Use the seeded target_vehicle.json rows
    # (the default reference) keyed by SDV name.
    try:
        seed = config_loader.load_seed_sections()
        seed = ({s["key"]: s["data"] for s in seed}
                if isinstance(seed, list) else seed)
        seed_rows = ((seed.get("target_vehicle") or {}).get("rows")) or []
        match = next((r for r in seed_rows
                      if str(r.get("sdv", "")).strip().upper() == up), None)
        if match:
            for part in ("driv", "dyn"):
                if out.get(part):
                    out[part]["target_index"] = match.get(part)
    except Exception:
        pass
    return out


def pj_share(bp, p):
    """% share of priority p breakpoints among all breakpoints (J8/9/10)."""
    tot = sum(bp[q]["total"] for q in (1, 2, 3))
    return 100.0 * bp[p]["total"] / tot if tot else 0.0


# --------------------------------------------------------------- events DB (OPEN DATABASE)

@api.get("/events")
async def list_events(search: Optional[str] = None, sdv: Optional[str] = None,
                      skip: int = 0, limit: int = 50):
    q = {}
    if sdv:
        q["sdv"] = sdv
    total = await db.events.count_documents(q)
    cur = db.events.find(q, {"_id": 0}).skip(skip).limit(min(limit, 500))
    events = await cur.to_list(min(limit, 500))
    if search:
        s = search.lower()
        events = [e for e in events if s in json.dumps(e["channels"]).lower()
                  or s in e["sdv"].lower()]
    return {"total": total, "events": events}


@api.put("/events/{event_id}")
async def update_event(event_id: str, payload: dict = Body(...)):
    ev = await db.events.find_one({"id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(404, "Event not found")
    channels = payload.get("channels")
    if channels:
        clean = {k.replace(".", "\u00b7"): v for k, v in channels.items()}
        await db.events.update_one({"id": event_id}, {"$set": {"channels": clean}})
        await moniteur(f"Event {event_id[:8]} updated in database")
    return await db.events.find_one({"id": event_id}, {"_id": 0})


@api.delete("/events/{event_id}")
async def delete_event(event_id: str):
    res = await db.events.delete_one({"id": event_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "Event not found")
    await moniteur(f"Event {event_id[:8]} deleted from database")
    return {"ok": True}


# --------------------------------------------------------------- config sheets

@api.get("/config")
async def all_config():
    return await get_config()


@api.get("/config/{section}")
async def one_config(section: str):
    return await get_config(section)


@api.put("/config/{section}")
async def put_config(section: str, payload: dict = Body(...)):
    doc = await db.config.find_one({"section": section})
    if not doc:
        raise HTTPException(404, f"Unknown config section {section}")
    await db.config.update_one({"section": section},
                               {"$set": {"data": payload.get("data")}})
    await moniteur(f"Configuration sheet '{section}' modified")
    return {"ok": True}


@api.post("/config/reset")
async def reset_config():
    await seed_if_needed(force=True)
    return {"ok": True}


@api.get("/layout/{name}")
async def layout(name: str):
    try:
        return config_loader.load_layout(name)
    except KeyError:
        raise HTTPException(404, "Unknown layout")


# --------------------------------------------------------------- logs

@api.get("/logs")
async def logs(limit: int = 200):
    rows = await db.macro_log.find({}, {"_id": 0}).sort("ts", -1).limit(limit).to_list(limit)
    return rows


# --------------------------------------------------------------- reports

@api.post("/report/{fmt}")
async def create_report(fmt: str, payload: dict = Body(default={})):
    if fmt not in ("pptx", "pdf", "docx"):
        raise HTTPException(400, "fmt must be pptx, pdf, or docx")
    project = await get_project()
    glob = await db.rating_global.find_one({}, {"_id": 0})
    rows = await db.sdv_results.find({}, {"_id": 0}).sort("order", 1).to_list(200)
    if not project or not rows:
        raise HTTPException(400, "Calculate the rating before creating a report")
    cfg = await get_config()
    charts_cfg = {k.strip().upper(): v for k, v in cfg["chart_params"].items()}
    charts = {}
    events_by_sdv = {}
    for r in rows:
        events = await db.events.find({"sdv": r["name"]}, {"_id": 0}).to_list(5000)
        events_by_sdv[r["name"]] = events
        params = charts_cfg.get(r["name"].strip().upper(), [])
        active = next((p for p in params if p.get("active")), None)
        x_name = (active or {}).get("x") or "Vehicle Speed"
        y_name = (active or {}).get("y") or "AccelerationChassis"
        pts = []
        for ev in events:
            x = get_channel(ev["channels"], x_name)
            y = get_channel(ev["channels"], y_name)
            try:
                pts.append({"x": float(x), "y": float(y),
                            "color": (ev.get("driv") or {}).get("color")})
            except (TypeError, ValueError):
                continue
        png_buf = report_builder.scatter_png(pts, x_name, y_name, r["name"])
        charts[r["name"]] = {"png": png_buf.getvalue() if png_buf else None}
    data = {"project": project, "global": glob, "sdv_results": rows,
            "charts": charts, "events_by_sdv": events_by_sdv,
            "doc_versions": payload.get("doc_versions") or []}
    out = os.path.join(tempfile.gettempdir(), f"ODRIV_report.{fmt}")
    report_fields = payload.get("report_fields")
    if fmt == "pptx":
        report_builder.build_pptx(data, out, report_fields=report_fields)
        media = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    elif fmt == "pdf":
        report_builder.build_pdf(data, out)
        media = "application/pdf"
    else:
        docx_builder.build_docx(data, out, report_fields=report_fields)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    await moniteur(f"Report generated ({fmt.upper()})")
    fname = f"ODRIV_{(project.get('name_code') or 'report').replace(' ', '_')}.{fmt}"
    return FileResponse(out, filename=fname, media_type=media)


app.include_router(api)

# ----------------------------------------------------------- static frontend
# One-click mode: if frontend/build exists, serve the SPA from this process.
FRONTEND_BUILD = ROOT_DIR.parent / "frontend" / "build"
if FRONTEND_BUILD.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/static", StaticFiles(directory=FRONTEND_BUILD / "static"),
              name="static")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        candidate = FRONTEND_BUILD / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_BUILD / "index.html")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
