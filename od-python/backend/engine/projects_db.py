"""Saved-projects database — reads the source tool's Access database
(_OdrivDB_*.accdb) so a processed project is persisted as a distinct record that
can be browsed, reopened, and compared, exactly like the legacy tool.

Access schema reproduced (table `projet`, 17 columns):
    ID, DateCreation, code, droopy, gears, energy, priority, milestone, aera,
    target, software, target_vehicle, Version, Mode, Uniquename, NbGear, ColonneDb

plus the per-project event payload (the Access `dataId` + `dataSub1/2/3` tables,
which store every classified event's channels). Here the events are stored as a
JSON snapshot attached to the saved record, which is the faithful equivalent for
a file-based deployment.

Storage backend is the same Mongo-style `db` the rest of the app uses
(real MongoDB when available, else mongomock snapshotted to odriv_data.json), so
saved projects persist across restarts with zero external services.
"""
from datetime import datetime, timezone
import uuid


# Map our internal project fields -> the Access `projet` column names, so a
# saved record is shaped exactly like a row of the legacy database.
def build_uniquename(project, milestone_num, nb_gear):
    """Reproduce the Access `Uniquename` composite key:
    software_code_gears_energy_milestone_area_target_software_vehicle_version."""
    parts = [
        project.get("software_milestone") or "",
        project.get("name_code") or "",
        project.get("gears") or project.get("gearbox") or "",
        (project.get("fuel") or "").upper(),
        str(milestone_num),
        project.get("area") or "",
        project.get("priority") or "",
        project.get("software_milestone") or "",
        project.get("target_vehicle") or "",
        "V" + str(project.get("version") or "4.6").lstrip("Vv"),
    ]
    return "_".join(str(p) for p in parts)


def project_to_record(project, milestone_num, sdv_results, global_results,
                      event_count, per_sdv_counts):
    """Build a saved-project record in the Access `projet` shape + results."""
    nb_gear = project.get("number_of_gears") or ""
    uniquename = build_uniquename(project, milestone_num, nb_gear)
    now = datetime.now(timezone.utc)
    return {
        "id": str(uuid.uuid4()),
        # ---- Access `projet` columns (faithful names) ----
        "DateCreation": now.isoformat(),
        "code": project.get("name_code") or "",
        "droopy": project.get("software_milestone") or "",
        "gears": project.get("gears") or project.get("gearbox") or "",
        "energy": (project.get("fuel") or "").upper(),
        "priority": project.get("priority") or "",
        "milestone": milestone_num,
        "aera": project.get("area") or "",          # (sic) matches Access spelling
        "target": project.get("priority") or "",
        "software": project.get("software_milestone") or "",
        "target_vehicle": project.get("target_vehicle") or "",
        "Version": "V" + str(project.get("version") or "4.6").lstrip("Vv"),
        "Mode": project.get("mode") or "AUTO",
        "Uniquename": uniquename,
        "NbGear": nb_gear,
        # ---- results snapshot (the dataId/dataSub equivalent + scorecard) ----
        "project": dict(project),
        "global": global_results,
        "sdv_count": len(sdv_results or []),
        "event_count": event_count,
        "per_sdv": per_sdv_counts or {},
        "driv_index": (global_results or {}).get("driv", {}).get("index"),
        "driv_verdict": (global_results or {}).get("driv", {}).get("verdict"),
        "dyn_index": (global_results or {}).get("dyn", {}).get("index"),
        "dyn_verdict": (global_results or {}).get("dyn", {}).get("verdict"),
    }


# Columns shown in the saved-projects browser (mirrors the Access `projet` grid)
PROJET_COLUMNS = ["DateCreation", "code", "energy", "gears", "NbGear",
                  "milestone", "aera", "Mode", "Version", "target_vehicle",
                  "driv_index", "driv_verdict", "dyn_index", "dyn_verdict",
                  "event_count", "sdv_count", "Uniquename"]
