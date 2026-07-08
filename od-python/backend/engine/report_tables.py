"""Shared matplotlib table images used by Word and PowerPoint ODrive reports."""
import io

from .classifier import MISSING, get_channel

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

SYNTHESIS_PARTS = (
    "Synthesis",
    "Points visualisation 1",
    "Points visualisation 2",
    "Highest Criticality to improve:",
    "Lowest Criticality to improve:",
)


def _fmt(v, nd=1):
    if v is None:
        return "-"
    try:
        return ("%." + str(nd) + "f") % float(v)
    except (TypeError, ValueError):
        return str(v)


def _png_bytes(buf):
    if buf is None:
        return None
    return buf.getvalue() if hasattr(buf, "getvalue") else buf


def _table_png(headers, rows, title=None, col_widths=None):
    if not rows:
        return None
    ncols = len(headers)
    fig_w = max(6.5, 0.9 * ncols)
    fig_h = max(1.8, 0.38 * (len(rows) + 1.5))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=120)
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=10, fontweight="bold", loc="left", pad=8)
    table = ax.table(cellText=rows, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.35)
    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor("#17375E")
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        elif col == 0:
            cell.get_text().set_ha("left")
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in range(len(rows) + 1):
                table[(row, i)].set_width(w)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _dot_char(status):
    return {"RED": "\u25cf", "ORANGE": "\u25cf", "GREEN": "\u25cf"}.get(status or "NONE", "\u25cb")


def _scorecard_png(data, title="Scorecard — use cases"):
    headers = ["USE CASE", "P1", "P2", "P3", "P1*", "P2*", "P3*", "Driv.", "Target", "Resp.", "Lowest event"]
    rows = []
    for sdv in data.get("sdv_results") or []:
        d = sdv.get("driv") or {}
        dy = sdv.get("dyn") or {}
        st = d.get("status") or {}
        sp = d.get("status_pred") or {}
        rows.append([
            (sdv.get("name") or "")[:34],
            _dot_char(st.get("1")), _dot_char(st.get("2")), _dot_char(st.get("3")),
            _dot_char(sp.get("1")), _dot_char(sp.get("2")), _dot_char(sp.get("3")),
            _fmt(d.get("index")), _fmt(d.get("target_index")), _fmt(dy.get("index")),
            str(d.get("lowest_event") or "-")[:28],
        ])
    return _table_png(headers, rows, title=title)


def _scorecard_png_chunks(data, chunk_size=14):
    """Return list of (title, png_bytesio) for chunked scorecard slides."""
    rows = data.get("sdv_results") or []
    chunks = [rows[i:i + chunk_size] for i in range(0, len(rows), chunk_size)] or [[]]
    out = []
    for ci, chunk in enumerate(chunks):
        title = "Scorecard — use cases (%d/%d)" % (ci + 1, len(chunks)) if len(chunks) > 1 else "Scorecard — use cases"
        sub = dict(data)
        sub["sdv_results"] = chunk
        png = _scorecard_png(sub, title=title)
        if png:
            out.append((title, png))
    return out


def _global_risk_png(glob):
    headers = ["", "Current status", "Forecast @ SOPM", "Global index", "Weighted % below target"]
    rows = []
    for part, label in (("driv", "DRIVABILITY"), ("dyn", "RESPONSIVENESS")):
        g = (glob or {}).get(part) or {}
        rows.append([
            label,
            g.get("verdict") or "-",
            g.get("verdict_pred") or "-",
            _fmt(g.get("index")),
            _fmt((g.get("rate_low") or 0) * 100, 2) + " %",
        ])
    return _table_png(headers, rows, title="Risk assessment for customer complaints")


def _project_home_png(project, glob):
    from datetime import datetime
    headers = ["Field", "Value"]
    p = project or {}
    g = glob or {}
    rows = [
        ["Project", p.get("name_code") or "-"],
        ["Vehicle mode", p.get("mode") or "-"],
        ["Fuel", p.get("fuel") or "-"],
        ["Gears", p.get("gears") or "-"],
        ["ODRIV milestone", p.get("odriv_milestone") or "-"],
        ["Drive version", "V%s" % str(p.get("version") or "-").lstrip("Vv")],
        ["Area", p.get("area") or "-"],
        ["Target vehicle", p.get("target_vehicle") or "-"],
        ["Drivability verdict", (g.get("driv") or {}).get("verdict") or "-"],
        ["Responsiveness verdict", (g.get("dyn") or {}).get("verdict") or "-"],
        ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
    ]
    return _table_png(headers, rows, title="Project summary")


def _sdv_synthesis_png(sdv, part_key):
    part = (sdv.get(part_key) or {})
    label = "DRIVABILITY" if part_key == "driv" else "RESPONSIVENESS"
    cnt = part.get("counts") or {}
    headers = ["Metric", "Value"]
    rows = [
        ["SDV", sdv.get("name") or "-"],
        ["Part", label],
        ["Events", str(sdv.get("n_events") or 0)],
        ["Index", _fmt(part.get("index"))],
        ["Target index", _fmt(part.get("target_index"))],
        ["Lowest event", str(part.get("lowest_event") or "-")],
        ["Red P1/P2/P3", "%s / %s / %s" % (cnt.get("RED_P1", 0), cnt.get("RED_P2", 0), cnt.get("RED_P3", 0))],
        ["Yellow P1/P2/P3", "%s / %s / %s" % (cnt.get("YELLOW_P1", 0), cnt.get("YELLOW_P2", 0), cnt.get("YELLOW_P3", 0))],
        ["Green P1/P2/P3", "%s / %s / %s" % (cnt.get("GREEN_P1", 0), cnt.get("GREEN_P2", 0), cnt.get("GREEN_P3", 0))],
    ]
    st = part.get("status") or {}
    sp = part.get("status_pred") or {}
    rows.append(["Status P1/P2/P3", "%s / %s / %s" % (st.get("1", "-"), st.get("2", "-"), st.get("3", "-"))])
    rows.append(["Forecast P1/P2/P3", "%s / %s / %s" % (sp.get("1", "-"), sp.get("2", "-"), sp.get("3", "-"))])
    return _table_png(headers, rows)


def _priority_table_png(events, part_key, filt):
    scored = []
    for ev in events or []:
        sc = (ev.get(part_key) or {})
        crit = sc.get("criticity")
        priority = sc.get("priority")
        if crit is None:
            continue
        scored.append((crit, priority, sc.get("color"), ev))
    if not scored:
        return None
    crit_values = sorted({c for c, _, _, _ in scored})
    if filt == "high":
        target_crit = crit_values[0]
    else:
        target_crit = crit_values[-1] if len(crit_values) > 1 else crit_values[0]
    filtered = [t for t in scored if t[0] == target_crit]
    if filt == "low" and len(crit_values) > 1:
        filtered = [t for t in scored if t[0] == crit_values[-1]]
    headers = ["Criticality", "Priority", "Color", "Sub event", "Index"]
    rows = []
    for crit, prio, color, ev in filtered[:12]:
        sc = ev.get(part_key) or {}
        sub = "-"
        chans = ev.get("channels") or {}
        if isinstance(chans, dict):
            val = get_channel(chans, "Sub Event Name")
            if val != MISSING and val is not None:
                sub = str(val)[:30]
        else:
            for ch in chans:
                if isinstance(ch, dict) and str(ch.get("name", "")).lower() in (
                    "sub event name", "sub_event_name"
                ):
                    sub = str(ch.get("value") or "-")[:30]
                    break
        rows.append([str(crit), str(prio or "-"), str(color or "-"), sub, _fmt(sc.get("indice_occ"), 2)])
    title = "Highest Criticality to improve" if filt == "high" else "Lowest Criticality to improve"
    return _table_png(headers, rows, title=title)


def _has_dyn_section(sdv):
    return bool((sdv.get("dyn") or {}).get("index") is not None)
