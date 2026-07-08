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

from docx import Document
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from engine.report_fields import normalize_report_fields
from engine.report_tables import (
    SYNTHESIS_PARTS,
    _global_risk_png,
    _has_dyn_section,
    _png_bytes,
    _priority_table_png,
    _project_home_png,
    _scorecard_png,
    _sdv_synthesis_png,
)
from engine.reports import _fmt_doc_version


TEMPLATE_NAME = "ODRIV_Report_Template.docx"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _template_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "source_artifacts", TEMPLATE_NAME))


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
        "SendFrom": f.get("from") or f.get("name") or "n/a",
        "TelFrom": f.get("sender_tel") or "n/a",
        "MailFrom": f.get("sender_email") or "n/a",
        "DepTV": f.get("sender_dept") or "n/a",
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
    fields = normalize_report_fields(project, report_fields)

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
