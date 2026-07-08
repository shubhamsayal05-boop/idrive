"""Word (.docx) ODrive report — mirrors the Excel VBA Report.bas deliverable.

Uses the embedded Word template from the original ODRIV workbook, fills cover
bookmarks/tables, inserts rating scorecard images, then appends per-SDV sections
(Heading 2 + Synthesis + scatter charts + priority tables) matching the Excel
tool structure.
"""
import io
import os
import shutil
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from engine.reports import _fmt, _fmt_doc_version, scatter_png

TEMPLATE_NAME = "ODRIV_Report_Template.docx"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SYNTHESIS_PARTS = (
    "Synthesis",
    "Points visualisation 1",
    "Points visualisation 2",
    "Highest Criticality to improve:",
    "Lowest Criticality to improve:",
)


def _template_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "source_artifacts", TEMPLATE_NAME))


def _table_png(headers, rows, title=None, col_widths=None):
    """Render a simple table as PNG bytes."""
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


def _scorecard_png(data):
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
    return _table_png(headers, rows, title="Scorecard — use cases")


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
    """Highest (filt='high') or lowest (filt='low') criticality events."""
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
        for ch in ev.get("channels") or []:
            if str(ch.get("name", "")).lower() in ("sub event name", "sub_event_name"):
                sub = str(ch.get("value") or "-")[:30]
                break
        rows.append([str(crit), str(prio or "-"), str(color or "-"), sub, _fmt(sc.get("indice_occ"), 2)])
    title = "Highest Criticality to improve" if filt == "high" else "Lowest Criticality to improve"
    return _table_png(headers, rows, title=title)


def _set_cell_text(cell, text):
    cell.text = str(text if text is not None else "")


def _fill_cover_tables(doc, project, fields, doc_versions):
    """Fill the six cover tables to match the Excel pre-fill form."""
    p = project or {}
    f = fields or {}
    domain = f.get("domain") or "DRIVABILITY-DYNAMISM"
    project_name = f.get("project") or p.get("name_code") or ""
    standard = f.get("standard") or "n/a"
    stage = f.get("stage") or "n/a"
    goal = f.get("goal") or "n/a"
    vehicle = f.get("car_number") or project_name or "n/a"

    if len(doc.tables) >= 1:
        t = doc.tables[0]
        _set_cell_text(t.rows[1].cells[1], domain)
        _set_cell_text(t.rows[2].cells[1], project_name)
        _set_cell_text(t.rows[3].cells[1], standard)
        _set_cell_text(t.rows[4].cells[1], stage)
        _set_cell_text(t.rows[5].cells[1], goal)

    if len(doc.tables) >= 2:
        recipients = f.get("recipients") or "For Information"
        goal_proj = f.get("goal_project") or recipients
        _set_cell_text(doc.tables[1].rows[0].cells[1], recipients)
        _set_cell_text(doc.tables[1].rows[1].cells[1], goal_proj)

    if len(doc.tables) >= 3:
        t = doc.tables[2]
        _set_cell_text(t.rows[0].cells[1], vehicle)
        _set_cell_text(t.rows[0].cells[2], f.get("vehicle_note") or "n/a")
        for label, soft_key, cal_key in (
            ("CMM", "cmm_soft", "cmm_calib"),
            ("TCU", "tcu_soft", "tcu_calib"),
            ("OBC", None, "obc_calib"),
            ("VCU", "vcu_soft", "vcu_calib"),
        ):
            for ri in range(1, len(t.rows)):
                if t.rows[ri].cells[0].text.strip() == label:
                    if soft_key and len(t.rows[ri].cells) > 2:
                        _set_cell_text(t.rows[ri].cells[2], f.get(soft_key) or "To be erased if %s is not used" % label)
                    if cal_key and len(t.rows[ri].cells) > 2:
                        row = ri + (0 if soft_key is None else 1)
                        if row < len(t.rows) and t.rows[row].cells[0].text.strip() == label:
                            _set_cell_text(t.rows[row].cells[2], f.get(cal_key) or "To be erased if %s is not used" % label)

    if len(doc.tables) >= 4 and doc_versions:
        t = doc.tables[3]
        links = {
            "self-learning tool": "http://docinfogroupe.inetpsa.com/ead/doc/ref.01471_17_01042/v.vc/fiche",
            "event collector": "http://docinfogroupe.inetpsa.com/ead/doc/ref.01470_16_00083/v.vc/fiche",
            "objective evaluation": "http://docinfogroupe.inetpsa.com/ead/doc/ref.01470_15_00987/v.vc/fiche",
            "experiment": "http://docinfogroupe.inetpsa.com/ead/doc/ref.01472_17_03797/v.vc/fiche",
            "odriv": "http://docinfogroupe.inetpsa.com/ead/doc/ref.01470_16_00345/v.vc/fiche",
        }
        for ri in range(1, len(t.rows)):
            name = t.rows[ri].cells[0].text.strip().lower()
            for key, url in links.items():
                if key in name:
                    _set_cell_text(t.rows[ri].cells[1], url)
                    break
            for dv in doc_versions:
                if isinstance(dv, dict) and dv.get("name", "").lower() in name:
                    _set_cell_text(t.rows[ri].cells[2], dv.get("version") or "")
                    break
            if "odriv" in name and doc_versions:
                ver = _fmt_doc_version(doc_versions[-1])
                if ver and ver != "-":
                    _set_cell_text(t.rows[ri].cells[2], ver)


def _make_run_with_text(text):
    from docx.oxml import OxmlElement
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    return r


def _replace_bookmark_content(doc, bookmark_name, text=None, image_bytes=None, width_in=6.2):
    """Replace content inside a Word bookmark with text and/or an image."""
    body = doc.element.body
    for bm_start in body.iter("{%s}bookmarkStart" % W_NS):
        if bm_start.get("{%s}name" % W_NS) != bookmark_name:
            continue
        bm_id = bm_start.get("{%s}id" % W_NS)
        parent = bm_start.getparent()
        nxt = bm_start.getnext()
        to_remove = []
        while nxt is not None:
            if nxt.tag == "{%s}bookmarkEnd" % W_NS and nxt.get("{%s}id" % W_NS) == bm_id:
                to_remove.append(nxt)
                break
            to_remove.append(nxt)
            nxt = nxt.getnext()
        for node in to_remove:
            parent.remove(node)
        if text:
            parent.insert(parent.index(bm_start) + 1, _make_run_with_text(text))
        if image_bytes:
            para_el = parent
            while para_el is not None and para_el.tag != "{%s}p" % W_NS:
                para_el = para_el.getparent()
            if para_el is not None:
                for p in doc.paragraphs:
                    if p._p is para_el:
                        p.add_run().add_picture(io.BytesIO(image_bytes), width=Inches(width_in))
                        break
        return True
    return False


def _find_paragraph(doc, text_fragment):
    frag = text_fragment.strip().lower()
    for p in doc.paragraphs:
        if frag in p.text.strip().lower():
            return p
    return None


def _insert_page_break_before(paragraph):
    p = paragraph.insert_paragraph_before("")
    run = p.add_run()
    run.add_break(WD_BREAK.PAGE)
    return p


def _add_bullet_section(paragraph, title):
    p = paragraph.insert_paragraph_before("")
    run = p.add_run(title)
    run.bold = True
    run.font.size = Pt(12)
    try:
        p.style = "List Paragraph"
    except KeyError:
        pass
    return p


def _png_bytes(buf):
    if buf is None:
        return None
    return buf.getvalue() if hasattr(buf, "getvalue") else buf


def _add_image_after(paragraph, image_bytes, width_in=6.2):
    p = paragraph.insert_paragraph_before("")
    raw = _png_bytes(image_bytes)
    if raw:
        p.add_run().add_picture(io.BytesIO(raw), width=Inches(width_in))
    return p


def _add_heading_before(paragraph, text):
    p = paragraph.insert_paragraph_before(text)
    for style_name in ("Heading 2", "Titre 2", "Title 2"):
        try:
            p.style = style_name
            break
        except KeyError:
            continue
    for run in p.runs:
        run.bold = True
        run.font.size = Pt(14)
    return p


def _has_dyn_section(sdv):
    return bool((sdv.get("dyn") or {}).get("index") is not None)


def _insert_sdv_sections(doc, data, events_by_sdv, charts):
    annex_p = _find_paragraph(doc, "ANNEXES")
    if annex_p is None:
        annex_p = doc.paragraphs[-1]

    sdv_list = data.get("sdv_results") or []
    for j, sdv in enumerate(sdv_list):
        name = sdv.get("name") or "SDV"
        events = events_by_sdv.get(name) or []
        for t, part_key, part_label in (
            (1, "driv", "DRIVABILITY"),
            (2, "dyn", "RESPONSIVENESS"),
        ):
            if t == 2 and not _has_dyn_section(sdv):
                continue
            if t == 2 and not (sdv.get("dyn") or {}):
                continue
            if j > 0 or t > 1:
                _insert_page_break_before(annex_p)

            heading = "2.%d.%d %s %s" % (j + 1, t, name.upper(), part_label)
            anchor = _add_heading_before(annex_p, heading)

            # 1 — Synthesis
            syn = _add_bullet_section(annex_p, SYNTHESIS_PARTS[0])
            syn_png = _sdv_synthesis_png(sdv, part_key)
            if syn_png:
                _add_image_after(annex_p, syn_png)

            # 2 — Points visualisation 1 (scatter)
            chart = (charts or {}).get(name) or {}
            png = chart.get("png")
            if png:
                _add_bullet_section(annex_p, SYNTHESIS_PARTS[1])
                _add_image_after(annex_p, png)

            # 4/5 — priority tables
            hi = _priority_table_png(events, part_key, "high")
            if hi:
                _add_bullet_section(annex_p, SYNTHESIS_PARTS[3])
                _add_image_after(annex_p, hi)
            lo = _priority_table_png(events, part_key, "low")
            if lo:
                _add_bullet_section(annex_p, SYNTHESIS_PARTS[4])
                _add_image_after(annex_p, lo)

            del anchor, syn


def _apply_bookmark_fields(doc, project, fields):
    p = project or {}
    f = fields or {}
    mapping = {
        "ProjectHead": f.get("project") or p.get("name_code") or "",
        "Signet1": f.get("project") or p.get("name_code") or "",
        "tetTabl1_1": f.get("project") or p.get("name_code") or "",
        "tetTabl1_2": f.get("car_number") or p.get("name_code") or "",
        "Domains": f.get("domain") or "DRIVABILITY-DYNAMISM",
        "Standars": f.get("standard") or "n/a",
        "Stages": f.get("stage") or "n/a",
        "Goals": f.get("goal") or "n/a",
        "Places": "%s %s" % (f.get("site") or "Place, n/a", datetime.now().strftime("%m/%d/%Y")),
        "Signet7": f.get("site") or "Place, n/a",
        "LocDatTest": f.get("loc_date_test") or "- Location and date of test: n/a",
        "ClimCond": f.get("climate") or "n/a",
        "AcStatus": f.get("ac_status") or "n/a",
        "vehOption": f.get("vehicle_options") or "n/a",
        "SendFrom": f.get("sender_name") or "From:",
        "TelFrom": f.get("sender_tel") or "Tél.:",
        "MailFrom": f.get("sender_email") or "Mail to:",
        "DepTV": f.get("sender_dept") or "Department:",
        "Global_Synthesis": f.get("synthesis") or "SYNTHESIS:",
    }
    for name, text in mapping.items():
        _replace_bookmark_content(doc, name, text=text)


def build_docx(data, out_path, report_fields=None):
    """Build an ODrive Word report matching the Excel tool layout."""
    tpl = _template_path()
    if not os.path.isfile(tpl):
        raise FileNotFoundError("Report template not found: %s" % tpl)
    shutil.copyfile(tpl, out_path)
    doc = Document(out_path)

    project = data.get("project") or {}
    glob = data.get("global") or {}
    fields = dict(report_fields or {})
    if not fields.get("project"):
        fields["project"] = project.get("name_code") or ""

    _fill_cover_tables(doc, project, fields, data.get("doc_versions") or [])
    _apply_bookmark_fields(doc, project, fields)

    # Embedded rating / home screenshots (SysHome, SysDr, SysDynT, SysDynGR)
    for bm, png in (
        ("SysHome", _project_home_png(project, glob)),
        ("SysDr", _global_risk_png(glob)),
        ("SysDynT", _scorecard_png(data)),
        ("SysDynGR", _scorecard_png(data)),
    ):
        if png:
            _replace_bookmark_content(doc, bm, image_bytes=_png_bytes(png))

    events_by_sdv = data.get("events_by_sdv") or {}
    _insert_sdv_sections(doc, data, events_by_sdv, data.get("charts") or {})

    doc.save(out_path)
    return out_path
