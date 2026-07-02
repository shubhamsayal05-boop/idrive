"""ODRIV scoring engine — the per-SDV and global compute chain.

Pipeline per SDV: agreement index per criterion, per-event aggregation
("C1 non-averaged, C2 averaged"), priority assignment from the speed x
acceleration grids, point colouring against Waterline/Target, occurrence
criticity (criticity table + threshold), the SDV index
J5 = 100*(1+sum(indice_occ)/N)^PUISS, status dots against the milestone
matrices, the weighted rate of low points, and the 3x3 global verdict.
"""
from .classifier import get_channel, _to_float, _check_single
from .event_color import classify_band, affect_color, new_tally

COLOR_ORDER = {"GREEN": 0, "YELLOW": 1, "RED": 2}
VERDICT_MATRIX = [
    ["Low Risk", "Low Risk", "Medium Risk"],
    ["Medium Risk", "Medium Risk", "High Risk"],
    ["High Risk", "High Risk", "High Risk"],
]


def criterion_index(note, wl, t, criticity):
    """Agreement index for one criterion -> (index, color) or None.

    C = (3-c)/2 ; ZF = COEF1*WL + COEF2*T = 2*WL - T ; piecewise penalty.
    Participates only when WL>0, T>0, 0<note<=10.
    """
    try:
        criticity = int(criticity)
    except (TypeError, ValueError):
        return None
    C = (3 - criticity) / 2.0
    if C <= 0:
        return None
    if wl is None or t is None or wl <= 0 or t <= 0:
        return None
    if note is None or not (0 < note <= 10):
        return None
    zf = 2 * wl - t
    denom = t - zf
    if denom == 0:
        return None
    color = "RED" if note < wl else ("YELLOW" if note < t else "GREEN")
    if note < zf:
        return -C, color
    note_t = 10 * (note - zf) / denom
    wl_t = 10 * (wl - zf) / denom
    t_t = 10.0
    if note_t < wl_t:
        idx = C * (2 * note_t - t_t - wl_t) / (t_t + wl_t)
    elif note_t < t_t:
        idx = C * (note_t - t_t) / (t_t + wl_t)
    else:
        idx = 0.0
    return idx, color


def _gate_configs(configs, project):
    """Select configs whose conditions match the project: a config is enabled
    only when Engine type, Gearbox type, Number of Gears, and Area ALL match
    (exact, case-insensitive; an empty condition list is a wildcard).

    If NO config matches, return empty -> the SDV gets no priority assigned and
    stays blank on the scorecard. For example, an SDV requiring EAT/EDCT with
    6-8 gears will not match an AT/10-speed vehicle, so that SDV is left blank
    (index None, 0 events scored)."""
    if not configs or not project:
        return configs
    engine = str(project.get("fuel") or "").strip().upper()
    gears_field = str(project.get("gearbox") or project.get("gears") or "").strip()
    # Normalize gearbox to its transmission-type token: HOME may store "AT",
    # "8AT", "AT 8-speed", etc. Strip a leading gear count and take the first
    # token so "8AT"/"10AT"/"AT 8-speed" all reduce to "AT" (matches config
    # gearbox cells). EAT/EDCT are preserved as distinct types.
    import re as _re
    gf = gears_field.upper()
    if gf == "MANUAL GEARBOX":
        gearbox = gf
    else:
        gf = _re.sub(r"^\d+\s*", "", gf)          # drop leading "8 " / "10"
        gearbox = gf.split(" ")[0] if gf else gf  # first token
    nbgear = str(project.get("number_of_gears") or project.get("gears") or "").strip()
    # area aliases -> canonical config labels
    _AREA_ALIAS = {"EU": "EUROPE", "NA": "NORTH AMERICA", "US": "NORTH AMERICA",
                   "USA": "NORTH AMERICA", "ROW": "WORLD"}
    area_raw = str(project.get("area") or "").strip().upper()
    area = _AREA_ALIAS.get(area_raw, area_raw)

    def ok(values, target):
        if not values:
            return True  # no condition on this axis = wildcard
        return target in {str(v).strip().upper() for v in values}

    matched = []
    for c in configs:
        cond = c.get("conditions", {})
        if (ok(cond.get("engine"), engine)
                and ok(cond.get("gearbox"), gearbox)
                and ok(cond.get("gears"), nbgear)
                and ok(cond.get("area"), area)):
            matched.append(c)
    return matched  # empty when nothing matches -> SDV stays unscored


def priority_and_cell(channels, configs):
    """Like priority_from_grid, but also returns the operating-cell key = the
    (row, column) cell of the priority grid the event lands in. Breakpoints are
    grouped by the grid-cell address, not by raw speed/throttle bands. Returns
    (priority, cell_key)."""
    if not configs:
        return 3, ("none",)
    for cfg in configs:
        if cfg.get("scalar") is not None and not cfg.get("rows"):
            return int(cfg["scalar"]), ("scalar",)
        rows = cfg.get("rows") or []
        col_vals = cfg.get("col_values") or []
        col_ch = cfg.get("col_channel") or cfg.get("col_param")
        row_ch = cfg.get("row_channel") or cfg.get("row_param")
        col_val = _to_float(get_channel(channels, col_ch)) if col_ch else None
        ci = _col_index(col_val, col_vals) if col_vals else 0

        if cfg.get("row_param") == "lever_transition":
            old = _norm_lever(get_channel(channels, "selector lever start"))
            new = _norm_lever(get_channel(channels, "selector lever end"))
            for ri, r in enumerate(rows):
                if r.get("old") == old and r.get("new") == new:
                    p = _pick(r["priorities"], ci)
                    if p:
                        return p, (ri, ci)
            continue

        non_banded = [r for r in rows if not r.get("band") and r.get("key") != "*"]
        if non_banded and cfg.get("row_param") != "lever_transition":
            rv = get_channel(channels, row_ch)
            rv_s = _norm_lever(rv) if rv is not None else None
            matched = None; mri = -1
            for ri, r in enumerate(non_banded):
                if str(r["key"]).strip().upper() == str(rv_s).strip().upper():
                    matched = r; mri = ri
                    break
            if matched is None:
                col_ps = {_pick(r["priorities"], ci) for r in non_banded}
                col_ps.discard(None)
                if len(col_ps) == 1:
                    return col_ps.pop(), ("rowkey", ci)
                matched = non_banded[0]; mri = 0
            p = _pick(matched["priorities"], ci)
            if p:
                return p, (mri, ci)

        row_val = _to_float(get_channel(channels, row_ch)) if row_ch else None
        # find row index for the cell key
        r = _match_row(row_val if row_val is not None else col_val, rows)
        if r:
            ri = rows.index(r) if r in rows else -1
            p = _pick(r["priorities"], ci)
            if p:
                return p, (ri, ci)
    return 3, ("default",)


def event_priority(channels, configs):
    """Event priority (1/2/3). Prefer an imported rating/priority channel if
    present (some AVL-DRIVE exports carry it), else the speed x accel grid."""
    for cand in ("Event Priority", "Sub Event Priority",
                 "Note Global, Sub Event Priority"):
        v = get_channel(channels, cand)
        try:
            iv = int(float(v))
            if iv in (1, 2, 3):
                return iv
        except (TypeError, ValueError):
            pass
    return priority_from_grid(channels, configs)


def _col_index(value, col_values):
    """Column index = last col whose threshold <= value (numeric axis)."""
    if value is None or not col_values:
        return 0
    ci = 0
    for i, c in enumerate(col_values):
        try:
            if value >= float(c):
                ci = i
        except (TypeError, ValueError):
            continue
    return ci


def _match_row(value, rows):
    """Pick a row by band (numeric, on magnitude) or discrete key match."""
    if not rows:
        return None
    # single implicit row
    if len(rows) == 1 and rows[0].get("key") == "*":
        return rows[0]
    # numeric banded rows — bands are positive magnitudes (e.g. |accel|),
    # so compare against abs(value)
    banded = [r for r in rows if r.get("band")]
    if banded and value is not None:
        v = abs(value)
        for r in banded:
            lo, hi = r["band"]
            if lo <= v < hi:
                return r
        return banded[-1]          # clamp to last band
    return None


def priority_from_grid(channels, configs):
    """P1/P2/P3 from a CONFIGURATIONS SEETINGS config. Handles every layout:
    2D grid (row bands x column axis), lever transition, discrete row keys,
    single implicit row, and scalar."""
    if not configs:
        return 3
    for cfg in configs:
        # scalar config -> one priority for the whole SDV
        if cfg.get("scalar") is not None and not cfg.get("rows"):
            return int(cfg["scalar"])
        rows = cfg.get("rows") or []
        col_vals = cfg.get("col_values") or []
        col_ch = cfg.get("col_channel") or cfg.get("col_param")
        row_ch = cfg.get("row_channel") or cfg.get("row_param")
        col_val = _to_float(get_channel(channels, col_ch)) if col_ch else None
        ci = _col_index(col_val, col_vals) if col_vals else 0

        # lever-transition layout
        if cfg.get("row_param") == "lever_transition":
            old = _norm_lever(get_channel(channels, "selector lever start"))
            new = _norm_lever(get_channel(channels, "selector lever end"))
            for r in rows:
                if r.get("old") == old and r.get("new") == new:
                    p = _pick(r["priorities"], ci)
                    if p:
                        return p
            continue

        # discrete row keys (e.g. Selector Lever P/R/N/D/M, Clim 0/1)
        non_banded = [r for r in rows if not r.get("band") and r.get("key") != "*"]
        if non_banded and cfg.get("row_param") != "lever_transition":
            rv = get_channel(channels, row_ch)
            rv_s = _norm_lever(rv) if rv is not None else None
            matched = None
            for r in non_banded:
                if str(r["key"]).strip().upper() == str(rv_s).strip().upper():
                    matched = r
                    break
            if matched is None:
                # row-key missing/unmatched: if all rows give the same priority
                # at this column, use it (common for Clim where both rows agree)
                col_ps = {_pick(r["priorities"], ci) for r in non_banded}
                col_ps.discard(None)
                if len(col_ps) == 1:
                    return col_ps.pop()
                matched = non_banded[0]
            p = _pick(matched["priorities"], ci)
            if p:
                return p

        # banded / implicit row x column grid
        row_val = _to_float(get_channel(channels, row_ch)) if row_ch else None
        r = _match_row(row_val if row_val is not None else col_val, rows)
        if r:
            p = _pick(r["priorities"], ci)
            if p:
                return p
    return 3


def _pick(prios, ci):
    if not prios:
        return None
    idx = ci if ci < len(prios) else len(prios) - 1
    try:
        p = int(prios[idx])
        return p if p in (1, 2, 3) else None
    except (TypeError, ValueError):
        return None


def _norm_lever(v):
    if v is None:
        return None
    s = str(v).strip().upper()
    # Lever position codes from CONFIGURATIONS sheet (verified):
    #   0=P, 1=R, 2=N, 3=D, 68=M, 69=S
    code = {"0": "P", "1": "R", "2": "N", "3": "D", "68": "M", "69": "S"}
    s2 = s.split(".")[0]
    return code.get(s2, s)

def criticity_level(color, priority, indice, criticity_cfg):
    """Map event colour + occurrence index to a drive-rating level and class.
    color may be 'RED+' to force the RED+ (deepest) level set by the
    deep-red escalation rule in score_event."""
    seuil = (criticity_cfg.get("seuil") or [-0.16, -0.16, -0.1])
    s = seuil[priority - 1] if priority - 1 < len(seuil) else -0.16
    if color == "RED+":
        level = "Red +"
    elif color == "RED":
        level = "Red"
    elif color == "YELLOW":
        level = "Orange" if indice < (s if s is not None else -0.16) else "Yellow"
    else:
        level = "Green"
    table = criticity_cfg.get("table") or {}
    occ = None
    if level in table and priority - 1 < len(table[level]):
        occ = table[level][priority - 1]
    return level, occ


def _prepare_criteria(criteria_rows, part):
    """Pre-parse the SDV's criteria rows for one part, ONCE, so score_event
    doesn't re-parse wl/t/crit for every event. Returns a list of tuples:
        (name, name_key, crit_i, crit_raw, wl, t, do_band)
    """
    key = "driv" if part == "driv" else "resp"
    out = []
    for name, row in criteria_rows.items():
        crit = row.get(key)
        try:
            crit_i = int(crit)
        except (TypeError, ValueError):
            continue
        wl, t = _to_float(row.get("wl")), _to_float(row.get("t"))
        do_band = wl is not None and t is not None and t != wl
        out.append((name, name.replace(".", "\u00b7"), crit_i, crit, wl, t,
                    do_band))
    return out


def score_event_prepared(channels, prepared, coefficients, priority, grid_cell,
                         criticity_cfg):
    """Like score_event, but takes pre-parsed criteria (`prepared`) and a
    pre-resolved (priority, grid_cell) so nothing fixed-per-SDV is recomputed
    per event. Functionally identical to score_event."""
    c1, c2 = [], []
    crit_colors = {}
    tally = new_tally()
    for name, name_key, crit_i, crit, wl, t, do_band in prepared:
        raw = _to_float(get_channel(channels, name))
        if do_band:
            classify_band(raw, wl, t, crit_i, tally)
        res = criterion_index(raw, wl, t, crit)
        if res is None:
            continue
        idx, color = res
        crit_colors[name_key] = color
        if crit_i == 1:
            c1.append(idx)
        else:
            c2.append(idx)
    if not c1 and not c2:
        return None
    indice = sum(c1) + (sum(c2) / len(c2) if c2 else 0.0)
    indice = max(indice, -1.0)
    color = affect_color(tally)
    coef = coefficients[str(priority)][color]
    level, occ = criticity_level(color, priority, indice, criticity_cfg)
    if color == "RED" and (tally["deep_red"][1] + tally["deep_red"][2]) > 0:
        level, occ = criticity_level("RED+", priority, indice, criticity_cfg)
    pt_green = sum(1 for c in crit_colors.values() if c == "GREEN")
    pt_yellow = sum(1 for c in crit_colors.values() if c == "YELLOW")
    pt_red = sum(1 for c in crit_colors.values() if c == "RED")
    return {
        "indice": round(indice, 4),
        "indice_occ": round(indice * coef / 100.0, 4),
        "color": color,
        "priority": priority,
        "criticity": level,
        "occurrence": occ,
        "crit_colors": crit_colors,
        "pt_green": pt_green,
        "pt_yellow": pt_yellow,
        "pt_red": pt_red,
        "cell": grid_cell,
    }


def score_event(channels, criteria_rows, part, coefficients, prior_cfgs,
                criticity_cfg):
    """Full per-event computation for one part ('driv'/'dyn').

    criteria_rows: {criterion_name: targets_row} for this SDV.
    """
    key = "driv" if part == "driv" else "resp"
    c1, c2 = [], []
    crit_colors = {}
    tally = new_tally()
    for name, row in criteria_rows.items():
        crit = row.get(key)
        try:
            crit_i = int(crit)
        except (TypeError, ValueError):
            continue
        wl, t = _to_float(row.get("wl")), _to_float(row.get("t"))
        raw = _to_float(get_channel(channels, name))
        # band tally for the event color (C3 included
        # in the tally only as informational — gate uses tiers 1 & 2)
        if wl is not None and t is not None and t != wl:
            classify_band(raw, wl, t, crit_i, tally)
        # agreement index contribution (C3 excluded: weight 0)
        res = criterion_index(raw, wl, t, crit)
        if res is None:
            continue
        idx, color = res
        crit_colors[name.replace(".", "\u00b7")] = color
        if crit_i == 1:
            c1.append(idx)
        else:
            c2.append(idx)
    if not c1 and not c2:
        return None
    indice = sum(c1) + (sum(c2) / len(c2) if c2 else 0.0)
    indice = max(indice, -1.0)  # hard clamp
    color = affect_color(tally)              # C1-gated, C2-majority cascade
    priority, grid_cell = priority_and_cell(channels, prior_cfgs)
    coef = coefficients[str(priority)][color]
    level, occ = criticity_level(color, priority, indice, criticity_cfg)
    # Deep-red escalation: an event already rated RED is escalated to "RED +"
    # when at least one of its criteria with a numeric criticity tier != 3 falls
    # in the deepest-red band (value < waterline - (target - waterline)). That
    # band is tracked per tier in tally['deep_red']; tiers 1 and 2 are active.
    if color == "RED" and (tally["deep_red"][1] + tally["deep_red"][2]) > 0:
        level, occ = criticity_level("RED+", priority, indice, criticity_cfg)
    # per-point color counts (criteria below target = breakpoints), for dot rule
    pt_green = sum(1 for c in crit_colors.values() if c == "GREEN")
    pt_yellow = sum(1 for c in crit_colors.values() if c == "YELLOW")
    pt_red = sum(1 for c in crit_colors.values() if c == "RED")
    # operating-cell key = the priority-grid cell (row index, column index) the
    # event maps to. Breakpoints are grouped by this grid-cell address, so
    # events in the same grid cell collapse to one breakpoint in the per-SDV
    # summary counts.
    cell = grid_cell
    return {
        "indice": round(indice, 4),
        "indice_occ": round(indice * coef / 100.0, 4),
        "color": color,
        "priority": priority,
        "criticity": level,
        "occurrence": occ,
        "crit_colors": crit_colors,
        "pt_green": pt_green,
        "pt_yellow": pt_yellow,
        "pt_red": pt_red,
        "cell": cell,
    }


def sdv_index(event_scores, puiss):
    """IndiceSDV = 1 + sum(indice_occ)/N ; J5 = round(100*IndiceSDV^PUISS, 1)."""
    n = len(event_scores)
    if n == 0:
        return None
    base = 1.0 + sum(e["indice_occ"] for e in event_scores) / n
    return round(100 * (max(base, 0.0) ** puiss), 1)


def status_dots(event_scores, m_idx, block, coef_yellow, facteur_redplus):
    """Per-priority status dot via the verified Note_SDV rule (engine/dots.py).
    Targets come from this SDV's SETTINGS block at milestone m_idx."""
    from .dots import note_sdv_dots
    pct = block.get("pct", {})
    nmin = block.get("nmin", {})

    def g(tbl, key, default):
        arr = tbl.get(key)
        if arr and m_idx < len(arr) and arr[m_idx] is not None:
            return arr[m_idx]
        return default

    targets = {}
    for p in (1, 2, 3):
        targets["P%dR" % p] = g(pct, "P%dR" % p, [0, 0, 0][p - 1])
        targets["P%dO" % p] = g(pct, "P%dO" % p, [25, 50, 60][p - 1])
        targets["NP%dR" % p] = g(nmin, "P%dR" % p, 1) or 1
        targets["NP%dO" % p] = g(nmin, "P%dO" % p, 1) or 1
    return note_sdv_dots(event_scores, targets)


def low_point_fraction(event_scores, coef_yellow, facteur_redplus):
    n = len(event_scores)
    if n == 0:
        return 0.0
    redplus = sum(1 for e in event_scores if e["criticity"] == "Red +")
    red = sum(1 for e in event_scores if e["color"] == "RED") - redplus
    yellow = sum(1 for e in event_scores if e["color"] == "YELLOW")
    return (red + facteur_redplus * redplus + yellow * coef_yellow) / n


def counts_table(event_scores):
    table = {}
    total = len(event_scores)
    for color in ("GREEN", "YELLOW", "RED"):
        for p in (1, 2, 3):
            k = "%s_P%d" % (color, p)
            c = sum(1 for e in event_scores
                    if e["color"] == color and e["priority"] == p)
            table[k] = c
    table["total"] = total
    for p in (1, 2, 3):
        table["P%d_total" % p] = sum(1 for e in event_scores if e["priority"] == p)
    return table


def global_verdict(index_value, rate_low, m_idx, thr, globalpuiss):
    """3x3 global verdict decision matrix."""
    x = (index_value / 100.0) ** globalpuiss if index_value else 0.0
    if rate_low < thr["taux_vert_orange"][m_idx]:
        row = 0
    elif rate_low <= thr["taux_orange_rouge"][m_idx]:
        row = 1
    else:
        row = 2
    if x > thr["index_vert_orange"][m_idx]:
        col = 0
    elif x >= thr["index_orange_rouge"][m_idx]:
        col = 1
    else:
        col = 2
    return VERDICT_MATRIX[row][col], round(x, 4)


def milestone_index(project, configurations):
    label = str(project.get("odriv_milestone") or "")
    m = (configurations.get("milestones") or {}).get(label)
    try:
        m = int(m)
    except (TypeError, ValueError):
        m = 4
    return max(0, min(3, m - 1))


def calculate_rating(project, events, cfg, targets_lookup, canon_map):
    """Afficher_Calcul master loop -> (event_updates, sdv_results, global_results)."""
    sg = cfg["settings_global"]
    coefficients = sg["coefficients"]
    puiss = sg["constants"]["PUISS"]
    gpuiss = sg["constants"]["GLOBALPUISS"]
    calculs = cfg["calculs"]
    blocks = cfg["settings_blocks"]
    blocks_up = {k.strip().upper(): v for k, v in blocks.items()}
    prior_up = {k.strip().upper(): v for k, v in cfg["priorisation"].items()}
    tv_rows = {r["sdv"].strip().upper(): r for r in cfg["target_vehicle"]["rows"]}
    calculs_up = {k.strip().upper(): v for k, v in calculs.get("sdv", {}).items()}
    catalog = {c["name"].strip().upper(): c for c in cfg["catalog"]}

    grade = (project.get("priority") or "PREMIUM").strip().upper()
    coef_orange = calculs["coef_orange_mainstream"] if grade == "MAINSTREAM" \
        else calculs["coef_orange_premium"]
    coef_yellow = 1.0 / coef_orange
    facteur_redplus = calculs.get("facteur_redplus") or 2
    m_idx = milestone_index(project, cfg["configurations"])

    by_sdv = {}
    for ev in events:
        by_sdv.setdefault(ev["sdv"], []).append(ev)

    event_updates = {}
    sdv_results = []
    parts_acc = {"driv": [], "dyn": []}

    for sdv_name, evs in by_sdv.items():
        up = sdv_name.strip().upper()
        if len(evs) < 1:
            continue  # only skip SDVs with no events (Excel shows 1-2 event SDVs)
        criteria_rows = targets_lookup.get(up, {})
        if not criteria_rows:
            continue
        block = blocks_up.get(up, {})
        all_cfgs = prior_up.get(up, [])
        prior_cfgs = _gate_configs(all_cfgs, project)
        # Config gate: if the SDV defines configs but none match the
        # project's Engine/Gearbox/Gears/Area, no priority is assigned and the
        # SDV is left blank (Exit Sub). Skip it entirely.
        if all_cfgs and not prior_cfgs:
            continue
        cat = catalog.get(up, {})
        result = {"name": sdv_name, "group": cat.get("group", ""),
                  "order": cat.get("order", 999), "n_events": len(evs)}
        # --- precompute, ONCE per SDV, the things that don't vary per event ---
        # (1) each event's (priority, grid_cell) — depends only on channels, so
        #     resolve once and reuse for both the driv and dyn passes;
        # (2) the parsed criteria rows per part — wl/t/crit as numbers, so
        #     score_event_prepared doesn't re-parse them for every event.
        ev_priority = [priority_and_cell(ev["channels"], prior_cfgs)
                       for ev in evs]
        prepared_by_part = {p: _prepare_criteria(criteria_rows, p)
                            for p in ("driv", "dyn")}
        crit_cfg = cfg["criticity"]
        for part in ("driv", "dyn"):
            scores = []
            lowest = None
            prepared = prepared_by_part[part]
            for ev, (priority, grid_cell) in zip(evs, ev_priority):
                sc = score_event_prepared(ev["channels"], prepared,
                                          coefficients, priority, grid_cell,
                                          crit_cfg)
                if sc is None:
                    continue
                scores.append(sc)
                event_updates.setdefault(ev["id"], {})[part] = sc
                if lowest is None or sc["indice_occ"] < lowest[0]:
                    sub = get_channel(ev["channels"], "Sub Event Name")
                    lowest = (sc["indice_occ"], str(sub) if sub != "__FFF__" else ev["id"][:8])
            if not scores:
                result[part] = None
                continue
            idx = sdv_index(scores, puiss)
            tvr = tv_rows.get(up, {})
            result[part] = {
                "index": idx,
                "target_index": tvr.get(part if part == "driv" else "dyn"),
                "status": status_dots(scores, m_idx, block, coef_yellow, facteur_redplus),
                "status_pred": status_dots(scores, 3, block, coef_yellow, facteur_redplus),
                "counts": counts_table(scores),
                "low_frac": round(low_point_fraction(scores, coef_yellow, facteur_redplus), 5),
                "lowest_event": (lowest[1] if lowest and lowest[0] < 0 else None),
            }
            sdv_cc = calculs_up.get(up, {})
            if idx is not None:
                parts_acc[part].append({
                    "sdv": sdv_name, "index": idx,
                    "low_frac": result[part]["low_frac"],
                    "weight": block.get("weight") or 10,
                    "taux": sdv_cc.get("taux") or 0.001,
                    "target": result[part]["target_index"],
                })
        sdv_results.append(result)

    global_results = {"milestone_idx": m_idx}
    for part in ("driv", "dyn"):
        acc = parts_acc[part]
        thr = cfg["thresholds"][part]
        if not acc:
            global_results[part] = None
            continue
        wsum = sum(a["weight"] for a in acc)
        g_index = round(sum(a["index"] * a["weight"] for a in acc) / wsum, 1) if wsum else None
        tg = [a for a in acc if a["target"] is not None]
        g_target = round(sum(a["target"] * a["weight"] for a in tg) /
                         sum(a["weight"] for a in tg), 1) if tg else None
        taux_sum = sum(a["taux"] for a in acc)
        rate_low = round(sum(a["taux"] * a["low_frac"] for a in acc) / taux_sum, 5) if taux_sum else 0.0
        verdict, x = global_verdict(g_index or 0, rate_low, m_idx, thr, gpuiss)
        verdict_pred, _ = global_verdict(g_index or 0, rate_low, 3, thr, gpuiss)
        target_x = ((g_target / 100.0) ** gpuiss) if g_target else None
        global_results[part] = {
            "index": g_index, "target_index": g_target,
            "normalized_x": x, "target_normalized_x": target_x,
            "rate_low": rate_low,
            "verdict": verdict, "verdict_pred": verdict_pred,
            "full_scale": thr["taux_pleine_echelle"][m_idx],
            # Risk-bar zones + markers. The index marker is placed at
            # (index/100)^GLOBALPUISS on a 0..1 (x100=%) axis — the SAME axis the
            # zone boundaries live on — exactly like Excel's AC11 = (CT3/100)^5.
            "bar": {
                "index_green_min": round(thr["index_vert_orange"][m_idx] * 100, 1),
                "index_yellow_min": round(thr["index_orange_rouge"][m_idx] * 100, 1),
                "taux_green_max": round(thr["taux_vert_orange"][m_idx] * 100, 3),
                "taux_yellow_max": round(thr["taux_orange_rouge"][m_idx] * 100, 3),
                "taux_full_scale": round(thr["taux_pleine_echelle"][m_idx] * 100, 3),
                # marker positions as normalized % (match Excel AC11/AC12 exactly)
                "tested_index_pos": round(x * 100, 2),
                "target_index_pos": (round(target_x * 100, 2)
                                     if target_x is not None else None),
                "tested_taux_pos": round(rate_low * 100, 3),
            },
        }
    sdv_results.sort(key=lambda r: r["order"])
    return event_updates, sdv_results, global_results
