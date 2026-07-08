"""Loads the ODRIV configuration extracted from the original workbook."""
import json
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

SECTION_FILES = {
    "catalog": "catalog.json",
    "definitions": "definitions.json",
    "structure": "structure.json",
    "settings_blocks": "settings_blocks.json",
    "settings_global": "settings_global.json",
    "targets": "targets.json",
    "calculs": "calculs.json",
    "criticity": "criticity.json",
    "thresholds": "thresholds.json",
    "priorisation": "priorisation.json",
    "target_vehicle": "target_vehicle.json",
    "chart_params": "chart_params.json",
    "configurations": "configurations.json",
    "graph_status": "graph_status.json",
}

LAYOUT_FILES = {
    "home": "layout_home.json",
    "rating": "layout_rating.json",
    "vierge": "layout_vierge.json",
}


def load_seed_sections():
    out = {}
    for name, fn in SECTION_FILES.items():
        with open(os.path.join(DATA_DIR, fn)) as f:
            out[name] = json.load(f)
    _apply_priorisation_corrections(out.get("priorisation"))
    return out


# Known discrepancies between the CONFIGURATIONS SEETINGS row-parameter LABEL and
# the actual SDV-sheet column the Excel grid is keyed against. Verified
# event-by-event against filled reference workbooks: for these SDVs the grid's
# "Throttle" row axis is the pedal CHANGE ("delta pedal"), not the absolute
# "Throttle Position". (e.g. Accel Load Increase: 56% match on Throttle Position
# vs 100% on delta pedal across 194 events.)
_PRIORITY_ROW_CHANNEL_FIX = {
    "ACCEL LOAD INCREASE": "delta pedal",
}


def _apply_priorisation_corrections(prio):
    if not isinstance(prio, dict):
        return
    for sdv, configs in prio.items():
        fix = _PRIORITY_ROW_CHANNEL_FIX.get(sdv.strip().upper())
        if not fix:
            continue
        for c in configs:
            # only redirect throttle-based row axes (leave any other layout alone)
            rc = (c.get("row_channel") or c.get("row_param") or "")
            if "throttle" in str(rc).lower():
                c["row_channel"] = fix


def load_layout(name):
    with open(os.path.join(DATA_DIR, LAYOUT_FILES[name])) as f:
        return json.load(f)


def build_canon_map(structure, catalog):
    """UPPERCASE -> canonical SDV name (structure keys are canonical)."""
    canon = {}
    for name in structure.keys():
        canon[name.strip().upper()] = name
    for item in catalog:
        canon.setdefault(item["name"].strip().upper(), item["name"])
    return canon


def canon_name(name, canon_map):
    return canon_map.get(str(name).strip().upper(), str(name).strip())


def build_targets_lookup(targets, project):
    """Targets rows filtered to the project's drive version / range / mode.

    Returns {SDV_UPPER: {criterion: row}}. Falls back progressively (drop
    mode filter, then range filter) so an unexpected project value can
    never empty the whole lookup and silently kill the scoring chain.
    """
    raw_v = str(project.get("version") or "4.6").upper().lstrip("V")
    version = "V" + raw_v
    available = {str(r.get("version")).upper() for r in targets}
    if version not in available:
        version = sorted(available)[-1] if available else version
    rng = (project.get("priority") or "PREMIUM").strip().upper()
    if rng not in ("PREMIUM", "MAINSTREAM"):
        rng = "PREMIUM"
    mode = (project.get("mode") or "AUTO").strip().upper()

    def build(use_range, use_mode):
        by_sdv = {}
        for row in targets:
            if str(row.get("version")).upper() != version:
                continue
            if use_range and rng and row.get("range") and str(row["range"]).strip().upper() != rng:
                continue
            if use_mode:
                modes = [m.strip().upper() for m in str(row.get("mode") or "").split(";") if m.strip()]
                if mode and modes and mode not in modes:
                    continue
            by_sdv.setdefault(row["sdv"].strip().upper(), {})[row["criteria"].strip()] = row
        return by_sdv

    for use_range, use_mode in ((True, True), (True, False), (False, False)):
        by_sdv = build(use_range, use_mode)
        if by_sdv:
            return by_sdv
    return {}
