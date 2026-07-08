"""Report generation — PowerPoint (.pptx) and PDF, mirroring the original
Report_PPT deliverable: title, project summary, risk scorecard, per-SDV pages
with scatter charts and summary tables.
"""
import io
import os
import tempfile
from datetime import datetime


def _fmt_doc_version(v):
    """doc_versions entries are dicts {name, version} (DocVersions D7:D10) or strings."""
    if isinstance(v, dict):
        return ("%s %s" % (v.get("name", ""), v.get("version", ""))).strip() or "-"
    return str(v)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, Image, PageBreak)

NAVY = (0x1E, 0x23, 0x36)
TEAL = (0x21, 0x59, 0x67)
DOT = {"RED": (0xFF, 0, 0), "ORANGE": (0xFF, 0xC0, 0), "GREEN": (0, 0xB0, 0x50),
       "NONE": (0xBF, 0xBF, 0xBF)}
VERDICT_COLOR = {"Low Risk": (0, 0xB0, 0x50), "Medium Risk": (0xFF, 0xC0, 0),
                 "High Risk": (0xFF, 0, 0)}
PT_COLOR = {"RED": "#FF0000", "YELLOW": "#E6C200", "GREEN": "#00B050"}


def scatter_png(events, x_name, y_name, title):
    """Build a colored scatter chart PNG for one SDV; returns bytes or None."""
    xs, ys, cs = [], [], []
    for ev in events:
        x, y = ev.get("x"), ev.get("y")
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y)
        cs.append(PT_COLOR.get(ev.get("color"), "#888888"))
    if not xs:
        return None
    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=110)
    ax.scatter(xs, ys, c=cs, s=42, edgecolors="#333333", linewidths=0.5, zorder=3)
    ax.set_xlabel(x_name, fontsize=9)
    ax.set_ylabel(y_name, fontsize=9)
    ax.set_title(title, fontsize=10, fontweight="bold")
    ax.grid(True, linewidth=0.4, alpha=0.5, zorder=0)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


def _fmt(v, nd=1):
    if v is None:
        return "-"
    try:
        return ("%."+str(nd)+"f") % float(v)
    except (TypeError, ValueError):
        return str(v)


# ================================================================ PPTX

def build_pptx(data, out_path):
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    project = data["project"]
    glob = data["global"] or {}

    # ---- title slide
    s = prs.slides.add_slide(blank)
    band = s.shapes.add_textbox(Inches(0.6), Inches(2.2), Inches(12), Inches(1.4))
    p = band.text_frame.paragraphs[0]
    p.text = "ODRIV — Objective Drivability Report"
    p.font.size = Pt(40)
    p.font.bold = True
    p.font.color.rgb = RGBColor(*NAVY)
    sub = s.shapes.add_textbox(Inches(0.6), Inches(3.6), Inches(12), Inches(2.2))
    tf = sub.text_frame
    lines = [
        "Project: %s" % (project.get("name_code") or "-"),
        "Vehicle mode: %s   Fuel: %s   Gears: %s" % (
            project.get("mode") or "-", project.get("fuel") or "-", project.get("gears") or "-"),
        "ODRIV milestone: %s   Drive version: V%s   Area: %s" % (
            project.get("odriv_milestone") or "-",
            str(project.get("version") or "-").lstrip("Vv"), project.get("area") or "-"),
        "Target vehicle: %s" % (project.get("target_vehicle") or "-"),
        "Document versions: %s" % (" / ".join(_fmt_doc_version(v) for v in data.get("doc_versions", []) if v) or "-"),
        "Generated: %s" % datetime.now().strftime("%Y-%m-%d %H:%M"),
    ]
    for i, line in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = line
        para.font.size = Pt(16)

    # ---- risk assessment slide
    s = prs.slides.add_slide(blank)
    _slide_title(s, "Risk assessment for customer complaints")
    y = 1.2
    for part, label in (("driv", "DRIVABILITY — comfort / disturbances"),
                        ("dyn", "RESPONSIVENESS — performance feel")):
        g = glob.get(part)
        box = s.shapes.add_textbox(Inches(0.6), Inches(y), Inches(6.2), Inches(2.4))
        tf = box.text_frame
        tf.paragraphs[0].text = label
        tf.paragraphs[0].font.bold = True
        tf.paragraphs[0].font.size = Pt(16)
        if g:
            rows = [("Current status", g["verdict"]),
                    ("Forecast status @ SOPM", g["verdict_pred"]),
                    ("Global index", _fmt(g["index"])),
                    ("Weighted % of events below target", _fmt((g["rate_low"] or 0) * 100, 2) + " %")]
        else:
            rows = [("Status", "No data")]
        for k, v in rows:
            para = tf.add_paragraph()
            para.text = "%s :  %s" % (k, v)
            para.font.size = Pt(13)
            if v in VERDICT_COLOR:
                para.font.bold = True
                para.font.color.rgb = RGBColor(*VERDICT_COLOR[v])
        y += 2.6

    # ---- scorecard table slides
    rows = data["sdv_results"]
    chunks = [rows[i:i + 14] for i in range(0, len(rows), 14)] or [[]]
    for ci, chunk in enumerate(chunks):
        s = prs.slides.add_slide(blank)
        _slide_title(s, "Scorecard — use cases (%d/%d)" % (ci + 1, len(chunks)))
        tbl_rows = len(chunk) + 1
        shape = s.shapes.add_table(tbl_rows, 11, Inches(0.4), Inches(1.1),
                                   Inches(12.5), Inches(0.34 * tbl_rows))
        table = shape.table
        heads = ["USE CASE", "P1", "P2", "P3", "P1*", "P2*", "P3*",
                 "Driv. Index", "Target", "Resp. Index", "Lowest event"]
        for i, h in enumerate(heads):
            c = table.cell(0, i)
            c.text = h
            c.text_frame.paragraphs[0].font.size = Pt(10)
            c.text_frame.paragraphs[0].font.bold = True
        for r, sdv in enumerate(chunk, 1):
            d = sdv.get("driv") or {}
            dy = sdv.get("dyn") or {}
            table.cell(r, 0).text = sdv["name"]
            for i, part_status in enumerate([(d.get("status") or {}).get(str(p), "NONE") for p in (1, 2, 3)] +
                                            [(d.get("status_pred") or {}).get(str(p), "NONE") for p in (1, 2, 3)]):
                c = table.cell(r, i + 1)
                c.text = "\u25CF"
                para = c.text_frame.paragraphs[0]
                para.font.color.rgb = RGBColor(*DOT.get(part_status, DOT["NONE"]))
                para.font.size = Pt(12)
                para.alignment = PP_ALIGN.CENTER
            table.cell(r, 7).text = _fmt(d.get("index"))
            table.cell(r, 8).text = _fmt(d.get("target_index"))
            table.cell(r, 9).text = _fmt(dy.get("index"))
            table.cell(r, 10).text = str(d.get("lowest_event") or "-")[:34]
            for i in range(11):
                for para in table.cell(r, i).text_frame.paragraphs:
                    if para.font.size is None:
                        para.font.size = Pt(9)

    # ---- per-SDV slides
    for sdv in rows:
        det = data["charts"].get(sdv["name"])
        s = prs.slides.add_slide(blank)
        _slide_title(s, sdv["name"])
        d = sdv.get("driv") or {}
        dy = sdv.get("dyn") or {}
        box = s.shapes.add_textbox(Inches(0.5), Inches(1.05), Inches(5.4), Inches(4.6))
        tf = box.text_frame
        tf.word_wrap = True
        stats = [
            ("Events", str(sdv["n_events"])),
            ("Drivability Index", _fmt(d.get("index"))),
            ("Target Index", _fmt(d.get("target_index"))),
            ("Responsiveness Index", _fmt(dy.get("index"))),
        ]
        cnt = d.get("counts") or {}
        for color in ("RED", "YELLOW", "GREEN"):
            stats.append((color.title() + " events (P1/P2/P3)",
                          "%d / %d / %d" % (cnt.get(color + "_P1", 0),
                                            cnt.get(color + "_P2", 0),
                                            cnt.get(color + "_P3", 0))))
        if d.get("lowest_event"):
            stats.append(("Lowest event", str(d["lowest_event"])))
        for i, (k, v) in enumerate(stats):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = "%s :  %s" % (k, v)
            para.font.size = Pt(13)
        if det and det.get("png"):
            s.shapes.add_picture(io.BytesIO(det["png"]), Inches(6.2), Inches(1.2),
                                 width=Inches(6.6))
    prs.save(out_path)
    return out_path


def _slide_title(slide, text):
    box = slide.shapes.add_textbox(Inches(0.4), Inches(0.25), Inches(12.4), Inches(0.7))
    p = box.text_frame.paragraphs[0]
    p.text = text
    p.font.size = Pt(24)
    p.font.bold = True
    p.font.color.rgb = RGBColor(*TEAL)


# ================================================================ PDF

def build_pdf(data, out_path):
    doc = SimpleDocTemplate(out_path, pagesize=landscape(A4),
                            leftMargin=1.2 * cm, rightMargin=1.2 * cm,
                            topMargin=1.2 * cm, bottomMargin=1.2 * cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Title"], textColor=colors.HexColor("#1E2336"))
    h2 = ParagraphStyle("h2x", parent=styles["Heading2"], textColor=colors.HexColor("#215967"))
    body = styles["Normal"]
    story = []
    project = data["project"]
    glob = data["global"] or {}

    story.append(Paragraph("ODRIV — Objective Drivability Report", h1))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Project: <b>%s</b> — Mode %s, Fuel %s, Gears %s — Milestone %s — Drive version V%s — Target vehicle %s" % (
        project.get("name_code") or "-", project.get("mode") or "-",
        project.get("fuel") or "-", project.get("gears") or "-",
        project.get("odriv_milestone") or "-",
        str(project.get("version") or "-").lstrip("Vv"),
        project.get("target_vehicle") or "-"), body))
    story.append(Paragraph("Generated: %s — Doc versions: %s" % (
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        " / ".join(_fmt_doc_version(v) for v in data.get("doc_versions", []) if v) or "-"), body))
    story.append(Spacer(1, 14))

    story.append(Paragraph("Risk assessment for customer complaints", h2))
    risk_rows = [["", "Current status", "Forecast @ SOPM", "Global index", "Weighted % below target"]]
    cellcolors = []
    for part, label in (("driv", "DRIVABILITY"), ("dyn", "RESPONSIVENESS")):
        g = glob.get(part)
        if g:
            risk_rows.append([label, g["verdict"], g["verdict_pred"],
                              _fmt(g["index"]), _fmt((g["rate_low"] or 0) * 100, 2) + " %"])
            cellcolors.append((g["verdict"], g["verdict_pred"]))
        else:
            risk_rows.append([label, "No data", "-", "-", "-"])
            cellcolors.append((None, None))
    t = Table(risk_rows, colWidths=[5 * cm, 4.5 * cm, 4.5 * cm, 4 * cm, 6 * cm])
    style = [("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17375E")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 9)]
    for i, (v1, v2) in enumerate(cellcolors, 1):
        for j, v in ((1, v1), (2, v2)):
            if v in VERDICT_COLOR:
                style.append(("BACKGROUND", (j, i), (j, i),
                              colors.Color(*[c / 255 for c in VERDICT_COLOR[v]])))
    t.setStyle(TableStyle(style))
    story.append(t)
    story.append(Spacer(1, 14))

    story.append(Paragraph("Scorecard — use cases", h2))
    heads = ["USE CASE", "P1", "P2", "P3", "P1*", "P2*", "P3*", "Driv.", "Target", "Resp.", "Lowest event"]
    rows = [heads]
    dots = []
    for sdv in data["sdv_results"]:
        d = sdv.get("driv") or {}
        dy = sdv.get("dyn") or {}
        st = d.get("status") or {}
        sp = d.get("status_pred") or {}
        rows.append([sdv["name"][:38], "\u25CF", "\u25CF", "\u25CF", "\u25CF", "\u25CF", "\u25CF",
                     _fmt(d.get("index")), _fmt(d.get("target_index")),
                     _fmt(dy.get("index")), str(d.get("lowest_event") or "-")[:30]])
        dots.append([st.get("1"), st.get("2"), st.get("3"), sp.get("1"), sp.get("2"), sp.get("3")])
    t = Table(rows, colWidths=[7.2 * cm] + [0.9 * cm] * 6 + [1.7 * cm] * 3 + [6 * cm],
              repeatRows=1)
    style = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17375E")),
             ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 7.5),
             ("ALIGN", (1, 0), (9, -1), "CENTER")]
    for i, drow in enumerate(dots, 1):
        for j, v in enumerate(drow):
            rgb = DOT.get(v or "NONE", DOT["NONE"])
            style.append(("TEXTCOLOR", (j + 1, i), (j + 1, i),
                          colors.Color(*[c / 255 for c in rgb])))
    t.setStyle(TableStyle(style))
    story.append(t)

    for sdv in data["sdv_results"]:
        det = data["charts"].get(sdv["name"])
        story.append(PageBreak())
        story.append(Paragraph(sdv["name"], h2))
        d = sdv.get("driv") or {}
        dy = sdv.get("dyn") or {}
        cnt = d.get("counts") or {}
        srows = [["Events", "Drivability Index", "Target", "Responsiveness Index",
                  "Red (P1/P2/P3)", "Yellow", "Green"],
                 [str(sdv["n_events"]), _fmt(d.get("index")), _fmt(d.get("target_index")),
                  _fmt(dy.get("index")),
                  "%d/%d/%d" % (cnt.get("RED_P1", 0), cnt.get("RED_P2", 0), cnt.get("RED_P3", 0)),
                  "%d/%d/%d" % (cnt.get("YELLOW_P1", 0), cnt.get("YELLOW_P2", 0), cnt.get("YELLOW_P3", 0)),
                  "%d/%d/%d" % (cnt.get("GREEN_P1", 0), cnt.get("GREEN_P2", 0), cnt.get("GREEN_P3", 0))]]
        t = Table(srows)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#538DD5")),
                               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        story.append(t)
        story.append(Spacer(1, 10))
        if det and det.get("png"):
            story.append(Image(io.BytesIO(det["png"]), width=16 * cm, height=9 * cm))
    doc.build(story)
    return out_path
