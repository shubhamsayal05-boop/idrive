"""Assemble report payload data matching the Excel VBA Report.bas inputs."""
from engine.classifier import MISSING, get_channel, _norm as _normch


# Chart axes that should use the physical signal rather than the scoring alias.
_CHART_AXIS_PREF = {"accelerationchassis": ["ax level", "ax mean"]}


def _parse_axis(v, default=None):
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in ("automatique", "auto", ""):
        return default
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _chart_num(channels, axis):
    pref = _CHART_AXIS_PREF.get(_normch(axis))
    if pref:
        for want in pref:
            for key, val in channels.items():
                k = _normch(key)
                kc = k.split(",", 1)[1].strip() if "," in k else k
                if kc == want:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
    val = get_channel(channels, axis)
    if val is MISSING or val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _chart_points(events, x_name, y_name, part_key):
    pts = []
    for ev in events:
        ch = ev.get("channels") or {}
        x = _chart_num(ch, x_name)
        y = _chart_num(ch, y_name)
        if x is None or y is None:
            continue
        comp = ev.get(part_key) or {}
        pts.append({"x": x, "y": y, "color": comp.get("color")})
    return pts


def _active_charts(charts_cfg, sdv_name):
    params = charts_cfg.get(sdv_name.strip().upper(), []) or []
    active = [p for p in params if p.get("active")]
    if not active:
        active = params[:2]
    while len(active) < 2:
        active.append(active[0] if active else {
            "name": "Graphique %d" % (len(active) + 1),
            "x": "Vehicle Speed",
            "y": "AccelerationChassis" if len(active) == 0 else "Engine Torque",
        })
    return active[:2]


def build_charts_for_sdv(events, charts_cfg, sdv_name, scatter_fn):
    """Return {driv: {1: png_bytes, 2: ...}, dyn: {...}} with part-colored scatters."""
    specs = _active_charts(charts_cfg, sdv_name)
    out = {"driv": {}, "dyn": {}}
    for idx, spec in enumerate(specs, start=1):
        x_name = spec.get("x") or "Vehicle Speed"
        y_name = spec.get("y") or "AccelerationChassis"
        xlim = (_parse_axis(spec.get("x_min")), _parse_axis(spec.get("x_max")))
        ylim = (_parse_axis(spec.get("y_min")), _parse_axis(spec.get("y_max")))
        title = "%s — %s" % (sdv_name, spec.get("name") or ("Graphique %d" % idx))
        for part in ("driv", "dyn"):
            pts = _chart_points(events, x_name, y_name, part)
            png = scatter_fn(
                pts, x_name, y_name, title,
                xlim=xlim if xlim[0] is not None and xlim[1] is not None else None,
                ylim=ylim if ylim[0] is not None and ylim[1] is not None else None,
            )
            out[part][idx] = png.getvalue() if png and hasattr(png, "getvalue") else png
    return out


def catalog_groups(catalog):
    groups = []
    seen = {}
    for entry in catalog or []:
        gname = entry.get("group") or "Other"
        if gname not in seen:
            seen[gname] = len(groups)
            groups.append({"name": gname, "sdvs": []})
        groups[seen[gname]]["sdvs"].append(entry.get("name"))
    return groups
