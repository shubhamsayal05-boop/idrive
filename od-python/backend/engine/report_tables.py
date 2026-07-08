"""Shared matplotlib table/chart images used by Word and PowerPoint ODrive reports.

Renders Excel-equivalent panels (HOME, RATING scorecard, SDV summary, priority tables)
so Python reports match the original ODRIV Excel tool output.
"""
import io

from .classifier import MISSING, get_channel

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle, Wedge

SYNTHESIS_PARTS = (
    "Synthesis",
    "Points visualisation 1",
    "Points visualisation 2",
    "Highest Criticality to improve:",
    "Lowest Criticality to improve:",
)

PART_LABELS = {"driv": "DRIVABILITY", "dyn": "DYNAMISM"}

CRIT_RANK = {
    "red +": 0, "red+": 0, "red": 1, "orange": 2, "yellow": 3, "green": 4,
    1: 0, 2: 1, 3: 2, 4: 3, 5: 4,
}

DOT_COLORS = {
    "RED": "#FF0000", "RED +": "#FF0000", "RED+": "#FF0000",
    "ORANGE": "#FFC000", "YELLOW": "#E6C200", "GREEN": "#00B050", "NONE": "#BFBFBF",
}

VERDICT_COLORS = {
    "Low Risk": "#00B050", "Medium Risk": "#FFC000", "High Risk": "#FF0000",
}

HEADBLUE = "#17375E"
TEAL = "#215967"


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


def _crit_rank(crit):
    if crit is None:
        return 99
    return CRIT_RANK.get(str(crit).strip().lower(), CRIT_RANK.get(crit, 50))


def _table_png(headers, rows, title=None, col_widths=None, row_colors=None, cell_colors=None):
    if not rows:
        return None
    ncols = len(headers)
    fig_w = max(7.0, 0.85 * ncols)
    fig_h = max(1.8, 0.36 * (len(rows) + 1.8))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=120)
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=10, fontweight="bold", loc="left", pad=8)
    table = ax.table(cellText=rows, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(7.5)
    table.scale(1, 1.3)
    for (row, col), cell in table.get_celld().items():
        if row == 0:
            cell.set_facecolor(HEADBLUE)
            cell.get_text().set_color("white")
            cell.get_text().set_weight("bold")
        elif col == 0:
            cell.get_text().set_ha("left")
        if row_colors and row > 0 and (row - 1) < len(row_colors) and row_colors[row - 1]:
            cell.set_facecolor(row_colors[row - 1])
        if cell_colors and row > 0 and (row - 1) < len(cell_colors):
            cc = cell_colors[row - 1]
            if cc and col < len(cc) and cc[col]:
                cell.get_text().set_color(cc[col])
                cell.get_text().set_weight("bold")
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in range(len(rows) + 1):
                table[(row, i)].set_width(w)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _dot_char(status):
    return "\u25cf"


def _scorecard_rows(data, catalog_groups, forecast=False):
    result_by = {r.get("name"): r for r in (data.get("sdv_results") or [])}
    headers = ["USE CASE", "P1", "P2", "P3", "Index", "Lowest event",
               "P1", "P2", "P3", "Index", "Lowest event"]
    rows, row_colors, cell_colors = [], [], []
    for grp in catalog_groups or []:
        rows.append([grp.get("name", "").upper(), "", "", "", "", "", "", "", "", "", ""])
        row_colors.append("#17375E")
        cell_colors.append([None] * 11)
        for sdv_name in grp.get("sdvs") or []:
            r = result_by.get(sdv_name)
            d = (r or {}).get("driv") or {}
            dy = (r or {}).get("dyn") or {}
            st = (d.get("status_pred") if forecast else d.get("status")) or {}
            st2 = (dy.get("status_pred") if forecast else dy.get("status")) or {}
            rows.append([
                (sdv_name or "")[:36],
                _dot_char(st.get("1")), _dot_char(st.get("2")), _dot_char(st.get("3")),
                _fmt(d.get("index")),
                str(d.get("lowest_event") or "-")[:28],
                _dot_char(st2.get("1")), _dot_char(st2.get("2")), _dot_char(st2.get("3")),
                _fmt(dy.get("index")),
                str(dy.get("lowest_event") or "-")[:28],
            ])
            row_colors.append("#F2F2F2" if not r else "#FFFFFF")
            cell_colors.append([
                None,
                DOT_COLORS.get(st.get("1"), DOT_COLORS["NONE"]),
                DOT_COLORS.get(st.get("2"), DOT_COLORS["NONE"]),
                DOT_COLORS.get(st.get("3"), DOT_COLORS["NONE"]),
                None, None,
                DOT_COLORS.get(st2.get("1"), DOT_COLORS["NONE"]),
                DOT_COLORS.get(st2.get("2"), DOT_COLORS["NONE"]),
                DOT_COLORS.get(st2.get("3"), DOT_COLORS["NONE"]),
                None, None,
            ])
    return headers, rows, row_colors, cell_colors


def _groups_from_data(data):
    groups = data.get("catalog_groups")
    if groups:
        return groups
    return [{"name": "Use cases", "sdvs": [r.get("name") for r in (data.get("sdv_results") or [])]}]


def _scorecard_png(data, title="Scorecard — use cases", forecast=False, catalog_groups=None):
    groups = catalog_groups if catalog_groups is not None else _groups_from_data(data)
    headers, rows, row_colors, cell_colors = _scorecard_rows(data, groups, forecast=forecast)
    if not rows:
        return None
    if forecast:
        title = title.replace("use cases", "forecast @ SOPM")
    return _table_png(headers, rows, title=title, row_colors=row_colors, cell_colors=cell_colors)


def _scorecard_png_chunks(data, chunk_size=14, forecast=False, catalog_groups=None):
    groups = catalog_groups if catalog_groups is not None else _groups_from_data(data)
    all_sdvs = [s for g in groups for s in (g.get("sdvs") or [])]
    chunks = [all_sdvs[i:i + chunk_size] for i in range(0, len(all_sdvs), chunk_size)] or [[]]
    out = []
    for ci, chunk in enumerate(chunks):
        sub_groups = []
        for g in groups:
            sdvs = [s for s in (g.get("sdvs") or []) if s in chunk]
            if sdvs:
                sub_groups.append({"name": g.get("name"), "sdvs": sdvs})
        title = "Scorecard — use cases (%d/%d)" % (ci + 1, len(chunks)) if len(chunks) > 1 else "Scorecard — use cases"
        png = _scorecard_png(data, title=title, forecast=forecast, catalog_groups=sub_groups)
        if png:
            out.append((title, png))
    return out


def _draw_marker_bar(ax, left, bottom, width, height, bar, axis="index"):
    if not bar:
        return
    if axis == "index":
        zones = [
            (0, bar.get("index_yellow_min", 55), "#FF0000"),
            (bar.get("index_yellow_min", 55), bar.get("index_green_min", 71), "#FFFF00"),
            (bar.get("index_green_min", 71), 100, "#00B050"),
        ]
        scale = width / 100.0
        tested = bar.get("tested_index_pos")
    else:
        fs = bar.get("taux_full_scale") or 12
        zones = [
            (0, bar.get("taux_green_max", 3), "#00B050"),
            (bar.get("taux_green_max", 3), bar.get("taux_yellow_max", 9), "#FFFF00"),
            (bar.get("taux_yellow_max", 9), fs, "#FF0000"),
        ]
        scale = width / fs
        tested = bar.get("tested_taux_pos")
    for zf, zt, color in zones:
        ax.add_patch(Rectangle((left + zf * scale, bottom), max(0, (zt - zf) * scale), height,
                               facecolor=color, edgecolor="white", linewidth=0.5))
    mid = bottom + height / 2
    if tested is not None:
        tx = left + tested * scale
        ax.add_patch(Polygon([[tx, mid + height * 0.35], [tx - height * 0.35, mid - height * 0.2],
                              [tx + height * 0.35, mid - height * 0.2]], closed=True, color="#000"))


def _global_risk_png(glob):
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 3.2), dpi=120)
    labels = [
        ("driv", "DRIVABILITY\ncomfort/disturbances (bump, shock, jerk, …)"),
        ("dyn", "RESPONSIVENESS\nPerformance feel (response delay, vehicle Agility, …)"),
    ]
    for ax, (part, label) in zip(axes, labels):
        ax.axis("off")
        g = (glob or {}).get(part) or {}
        verdict = g.get("verdict") or "-"
        vcolor = VERDICT_COLORS.get(verdict, "#777777")
        ax.text(0.01, 0.72, label, fontsize=8, fontweight="bold", va="top", transform=ax.transAxes)
        ax.add_patch(Rectangle((0.38, 0.45), 0.12, 0.45, facecolor=vcolor, edgecolor="#999"))
        ax.text(0.44, 0.67, verdict, fontsize=7, fontweight="bold", color="white", ha="center", va="center")
        ax.text(0.52, 0.78, "Forecast @ SOPM", fontsize=7, color="#444")
        ax.text(0.52, 0.68, g.get("verdict_pred") or "-", fontsize=8, fontweight="bold")
        ax.text(0.68, 0.78, "Global index", fontsize=7, color="#444")
        ax.text(0.68, 0.68, _fmt(g.get("index")), fontsize=9, fontweight="bold")
        ax.text(0.82, 0.78, "Weighted % below target", fontsize=7, color="#444")
        ax.text(0.82, 0.68, _fmt((g.get("rate_low") or 0) * 100, 2) + " %", fontsize=9, fontweight="bold")
        bar = g.get("bar") or {}
        _draw_marker_bar(ax, 0.38, 0.08, 0.55, 0.22, bar, axis="index")
        ax.text(0.30, 0.19, "index", fontsize=7, ha="right")
        _draw_marker_bar(ax, 0.38, 0.0, 0.55, 0.07, bar, axis="taux")
        ax.text(0.30, 0.035, "Weighted %\nof events\nbelow target", fontsize=6, ha="right", va="center")
    fig.suptitle("Risk assessment for customer complaints", fontsize=10, fontweight="bold", x=0.02, ha="left")
    buf = io.BytesIO()
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _project_home_png(project, glob, state=None):
    from datetime import datetime
    p = project or {}
    st = state or {}
    headers = ["Field", "Value"]
    rows = [
        ["Project ID / Code", p.get("name_code") or "-"],
        ["Mode", p.get("mode") or "-"],
        ["Fuel", p.get("fuel") or "-"],
        ["Gears", p.get("gears") or "-"],
        ["Priority", p.get("priority") or "-"],
        ["Version", "V%s" % str(p.get("version") or "-").lstrip("Vv")],
        ["ODRIV milestone", p.get("odriv_milestone") or "-"],
        ["Area", p.get("area") or "-"],
        ["Target vehicle", p.get("target_vehicle") or "-"],
        ["Events in DB", str(st.get("event_count") or "-")],
        ["SDV sheets generated", str(st.get("sdv_count") or "-")],
        ["Rating calculated", "Yes" if glob else "No"],
        ["Drivability verdict", (glob or {}).get("driv", {}).get("verdict") or "-"],
        ["Responsiveness verdict", (glob or {}).get("dyn", {}).get("verdict") or "-"],
        ["Generated", datetime.now().strftime("%Y-%m-%d %H:%M")],
    ]
    return _table_png(headers, rows, title="Project summary (HOME)")


def _gauge_ax(ax, cx, cy, r, p, value, target):
    pct = 0 if value is None else max(0, min(100, float(value)))
    ring = "#00B050" if target is not None and pct >= target else ("#FFC000" if pct >= 50 else "#FF0000")
    ax.add_patch(Wedge((cx, cy), r, 90, 90 - 360 * pct / 100, width=0.18, facecolor=ring, edgecolor="none"))
    ax.add_patch(Wedge((cx, cy), r, 0, 360, width=0.18, facecolor="#E6E6E6", edgecolor="none"))
    ax.text(cx, cy + 0.05, "P%d" % p, ha="center", va="center", fontsize=11, fontweight="bold")
    ax.text(cx, cy - 0.22, "-" if value is None else "%.0f%%" % pct, ha="center", va="center", fontsize=8)


def _sdv_summary_panel_png(summ, sdv_name, part_key, sdv_result=None):
    part = summ or {}
    if not part:
        return _sdv_synthesis_png(sdv_result or {}, part_key)
    label = PART_LABELS.get(part_key, part_key.upper())
    tbl = part.get("table") or {}
    fig = plt.figure(figsize=(8.5, 6.8), dpi=120)
    fig.suptitle("%s — %s SUMMARY" % (sdv_name, label), fontsize=11, fontweight="bold",
                 color=TEAL, x=0.02, ha="left")
    gs = fig.add_gridspec(3, 3, height_ratios=[0.9, 2.4, 0.8], hspace=0.35, wspace=0.25)

    axg = fig.add_subplot(gs[0, :])
    axg.axis("off")
    axg.set_xlim(0, 3)
    axg.set_ylim(0, 1)
    for i, p in enumerate((1, 2, 3)):
        gg = (part.get("gauges") or {}).get(p) or (part.get("gauges") or {}).get(str(p)) or {}
        _gauge_ax(axg, 0.5 + i, 0.55, 0.35, p, gg.get("green_pct"), gg.get("target"))

    ax = fig.add_subplot(gs[1, :2])
    ax.axis("off")
    headers = ["Color", "Px", "Events", "% tot", "BP", "% Px", "Target"]
    rows = []
    for p in (1, 2, 3):
        bp = (tbl.get("breakpoints") or {}).get(p) or (tbl.get("breakpoints") or {}).get(str(p)) or {}
        rows.append(["TOTAL", "P%d" % p, "", "", str(bp.get("total", 0)),
                     _fmt(tbl.get("pct_total_prio", {}).get(p), 1), ""])
    for color, key in (("Green", "green"), ("Yellow", "yellow"), ("Red", "red")):
        for p in (1, 2, 3):
            bp = (tbl.get("breakpoints") or {}).get(p) or (tbl.get("breakpoints") or {}).get(str(p)) or {}
            rows.append([color, "P%d" % p,
                         str(tbl.get("events", {}).get(key, "")) if p == 1 else "",
                         _fmt(tbl.get("pct_of_total", {}).get(key), 1) if p == 1 else "",
                         str(bp.get(key, 0)),
                         _fmt((tbl.get("pct_%s" % key) or {}).get(p), 1),
                         str((tbl.get("target_%s" % key) or {}).get(p, ""))])
    table = ax.table(cellText=rows, colLabels=headers, loc="center", cellLoc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(7)
    table.scale(1, 1.15)

    ax2 = fig.add_subplot(gs[1, 2])
    ax2.axis("off")
    pr = (sdv_result or {}).get(part_key) or {}
    idx_label = "Drivability Index" if part_key == "driv" else "Responsiveness Index"
    ax2.text(0.5, 0.82, idx_label, ha="center", fontsize=8, fontweight="bold", color="white",
             bbox=dict(boxstyle="square,pad=0.4", facecolor=TEAL, edgecolor="none"))
    ax2.text(0.5, 0.55, _fmt(part.get("index") or pr.get("index")), ha="center", fontsize=22, fontweight="bold")
    ax2.text(0.5, 0.25, "Target Index", ha="center", fontsize=8, fontweight="bold", color="white",
             bbox=dict(boxstyle="square,pad=0.4", facecolor=TEAL, edgecolor="none"))
    ax2.text(0.5, 0.05, _fmt(part.get("target_index") or pr.get("target_index")), ha="center", fontsize=16, fontweight="bold")

    ax3 = fig.add_subplot(gs[2, :])
    ax3.axis("off")
    cov = part.get("coverage") or {}
    cov_txt = "  ".join("P%d: %s" % (p, _fmt((cov.get(p) or cov.get(str(p)) or 0) * 100, 0) + "%")
                        for p in (1, 2, 3))
    ax3.text(0.02, 0.65, "Coverage rate achieved", fontsize=9, fontweight="bold")
    ax3.text(0.02, 0.25, cov_txt, fontsize=9)
    ax3.text(0.72, 0.25, "Overall: %s" % (_fmt((part.get("coverage_overall") or 0) * 100, 0) + "%"),
             fontsize=11, fontweight="bold")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


def _sdv_synthesis_png(sdv, part_key):
    part = (sdv.get(part_key) or {})
    label = PART_LABELS.get(part_key, part_key.upper())
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
        if crit is None:
            continue
        scored.append((_crit_rank(crit), crit, sc.get("priority"), sc.get("color"), sc.get("indice_occ"), ev))
    if not scored:
        return None
    ranks = sorted({s[0] for s in scored})
    target_rank = ranks[0] if filt == "high" else ranks[-1]
    filtered = [s for s in scored if s[0] == target_rank]
    filtered.sort(key=lambda s: (s[4] if s[4] is not None else 0))
    headers = ["Criticality", "Priority", "Color", "Sub event", "Indice occ."]
    rows, row_colors, cell_colors = [], [], []
    for _, crit, prio, color, occ, ev in filtered[:20]:
        sc = ev.get(part_key) or {}
        sub = "-"
        chans = ev.get("channels") or {}
        if isinstance(chans, dict):
            val = get_channel(chans, "Sub Event Name")
            if val != MISSING and val is not None:
                sub = str(val)[:34]
        else:
            for ch in chans:
                if isinstance(ch, dict) and str(ch.get("name", "")).lower() in (
                    "sub event name", "sub_event_name"
                ):
                    sub = str(ch.get("value") or "-")[:34]
                    break
        bg = {"RED": "#FFC7CE", "RED +": "#FFC7CE", "RED+": "#FFC7CE",
              "YELLOW": "#FFEB9C", "ORANGE": "#FFEB9C", "GREEN": "#C6EFCE"}.get(str(color or "").upper())
        rows.append([str(crit), "P%s" % (prio or "-"), str(color or "-"), sub, _fmt(sc.get("indice_occ"), 4)])
        row_colors.append(bg)
        cell_colors.append([None] * 5)
    title = "Highest Criticality to improve" if filt == "high" else "Lowest Criticality to improve"
    return _table_png(headers, rows, title=title, row_colors=row_colors, cell_colors=cell_colors)


def _has_dyn_section(sdv):
    return bool((sdv.get("dyn") or {}).get("index") is not None)


def part_label(part_key):
    return PART_LABELS.get(part_key, part_key.upper())
