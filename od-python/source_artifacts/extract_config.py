"""Extract the complete ODRIV configuration from the original .xlsm into JSON.

Run once: python3 extract_config.py
Outputs into /app/backend/engine/data/
"""
import json
import os
import re
import openpyxl

SRC = "/app/source_artifacts/ODRIV_v29_2_1_AT.xlsm"
OUT = "/app/backend/engine/data"
os.makedirs(OUT, exist_ok=True)

wb = openpyxl.load_workbook(SRC, data_only=True)


def save(name, obj):
    with open(os.path.join(OUT, name), "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False, default=str)
    print("wrote", name)


def rows_of(ws, max_r=None, max_c=None):
    return list(ws.iter_rows(min_row=1, max_row=max_r or ws.max_row,
                             max_col=max_c or ws.max_column, values_only=True))


# ------------------------------------------------------------ 1. catalog (RATING rows 23-98)
ws = wb["RATING"]
catalog = []
group = None
order = 0
for ri in range(23, 99):
    g = ws.cell(row=ri, column=2).value
    s = ws.cell(row=ri, column=4).value
    if g and str(g).strip():
        group = str(g).strip()
    elif s and str(s).strip():
        order += 1
        catalog.append({"name": str(s).strip(), "group": group, "order": order})
save("catalog.json", catalog)

# ------------------------------------------------------------ 2. DEFINITION SDV
ws = wb["DEFINITION SDV"]
rules = []
cur = None
for row in rows_of(ws, max_c=5):
    a, b, c, d, e = row
    if a is None and b is None:
        continue
    if b is not None and c is None and d is None and a is not None and str(b).strip() not in ("CONDITION",):
        # header row: ORDRE + SDV name
        if str(b).strip() == "COLONNE":
            continue
        cell_a = str(a).strip()
        if cell_a == "ORDRE":
            continue
        cur = {"order": int(float(a)), "sdv": str(b).strip(), "active": True, "conditions": []}
        rules.append(cur)
    elif b is not None and str(b).strip() == "COLONNE":
        continue
    elif cur is not None and b is not None and c is not None:
        val = "" if d is None else d
        try:
            grp = int(float(e)) if e is not None else 1
        except (TypeError, ValueError):
            grp = 1
        cur["conditions"].append({"column": str(b).strip(), "op": str(c).strip(),
                                  "value": val, "group": grp})
save("definitions.json", rules)

# ------------------------------------------------------------ 3. structure
ws = wb["structure"]
structure = {}
cur_sdv = None
for row in rows_of(ws, max_c=8):
    sdv_name = row[1]
    kind = row[2]
    disp = row[3]
    imp = row[4]
    if sdv_name and kind == "sheets":
        cur_sdv = str(sdv_name).strip()
        structure[cur_sdv] = {"columns": [], "data": [], "criteria": []}
    elif cur_sdv and kind in ("column", "data", "criteria") and disp:
        entry = {"name": str(disp).strip(), "import": str(imp).strip() if imp else None}
        structure[cur_sdv][kind + "s" if kind == "column" else kind].append(entry)
save("structure.json", structure)

# ------------------------------------------------------------ 4. SETTINGS blocks
ws = wb["SETTINGS"]
settings_blocks = {}
grid = rows_of(ws, max_c=12)
i = 0
known_titles = set()
while i < len(grid):
    row = grid[i]
    a = row[0]
    if a and isinstance(a, str) and a.strip() and a.strip() not in (
            "SETTINGS", "(Only data in pink can be modified)") and not a.startswith("%") \
            and a.strip() not in ("WEIGHT",):
        title = a.strip()
        # look ahead for %P1R within next 8 rows
        block = {}
        weight = None
        overall = None
        j = i + 1
        found = False
        while j < min(i + 16, len(grid)):
            r2 = grid[j]
            key = str(r2[0]).strip() if r2[0] else ""
            if key.startswith("%P"):
                block[key.lstrip("%")] = [r2[1], r2[2], r2[3], r2[4]]
                block["N" + key.lstrip("%")] = [r2[7], r2[8], r2[9], r2[10]]
                found = True
            elif key == "WEIGHT":
                weight = r2[2]
                overall = r2[10]
                break
            j += 1
        if found:
            settings_blocks[title] = {"pct": {k: v for k, v in block.items() if not k.startswith("N")},
                                      "nmin": {k[1:]: v for k, v in block.items() if k.startswith("N")},
                                      "weight": weight, "overall_min_pts": overall}
            i = j
    i += 1
save("settings_blocks.json", settings_blocks)

# global scoring constants (verified from SETTINGS sheet + blueprint)
save("settings_global.json", {
    "constants": {"COEF1": 2, "COEF2": -1, "COEF3": 0, "PUISS": 3, "GLOBALPUISS": 5,
                  "FORMS": "Recalibrée C1 non-moyennés C2 moyennés"},
    "coefficients": {"1": {"RED": 100, "YELLOW": 100, "GREEN": 10},
                     "2": {"RED": 80, "YELLOW": 80, "GREEN": 8},
                     "3": {"RED": 60, "YELLOW": 60, "GREEN": 6}},
})

# ------------------------------------------------------------ 5. TARGETS
ws = wb["TARGETS"]
targets = []
for row in rows_of(ws, max_c=10)[1:]:
    if not row[0] or not row[1]:
        continue
    targets.append({
        "sdv": str(row[0]).strip(), "criteria": str(row[1]).strip(),
        "range": str(row[2]).strip() if row[2] else None,
        "mode": str(row[3]).strip() if row[3] else None,
        "fuel": str(row[4]).strip() if row[4] else None,
        "version": str(row[5]).strip() if row[5] else None,
        "wl": row[6], "t": row[7],
        "resp": row[8], "driv": row[9],
    })
save("targets.json", targets)

# ------------------------------------------------------------ 6. Calculs
ws = wb["Calculs"]
calculs = {"facteur_redplus": ws["I1"].value, "nb_repet": ws["I2"].value,
           "coef_orange_mainstream": ws["I3"].value,
           "coef_orange_premium": ws["I4"].value, "sdv": {}}
for ri in range(5, 70):
    name = ws.cell(row=ri, column=2).value
    if not name or str(name).strip() == "Somme":
        continue
    calculs["sdv"][str(name).strip()] = {
        "taux": ws.cell(row=ri, column=3).value,
        "p_rates": [ws.cell(row=ri, column=4).value,
                    ws.cell(row=ri, column=5).value,
                    ws.cell(row=ri, column=6).value]}
save("calculs.json", calculs)

# ------------------------------------------------------------ 7. cfg_criticity
ws = wb["cfg_criticity"]
crit = {"table": {}, "seuil": {}}
for ri in range(4, 9):
    label = ws.cell(row=ri, column=3).value
    crit["table"][str(label).strip()] = [ws.cell(row=ri, column=4).value,
                                         ws.cell(row=ri, column=5).value,
                                         ws.cell(row=ri, column=6).value]
crit["seuil"] = [ws.cell(row=9, column=4).value, ws.cell(row=9, column=5).value,
                 ws.cell(row=9, column=6).value]
save("criticity.json", crit)

# ------------------------------------------------------------ 8. Graph_status thresholds
ws = wb["Graph_status"]


def thr(r):
    return [ws.cell(row=r, column=2).value, ws.cell(row=r, column=3).value,
            ws.cell(row=r, column=4).value, ws.cell(row=r, column=5).value]


save("thresholds.json", {
    "driv": {"index_vert_orange": thr(11), "index_orange_rouge": thr(12),
             "taux_vert_orange": thr(23), "taux_orange_rouge": thr(24),
             "taux_pleine_echelle": thr(25)},
    "dyn": {"index_vert_orange": thr(36), "index_orange_rouge": thr(37),
            "taux_vert_orange": thr(48), "taux_orange_rouge": thr(49),
            "taux_pleine_echelle": thr(50)},
})

# ------------------------------------------------------------ 9. CONFIGURATIONS SEETINGS (priorisation)
ws = wb["CONFIGURATIONS SEETINGS"]
prior = {}
g = rows_of(ws, max_c=35)
i = 0
cur_sdv = None
while i < len(g):
    row = g[i]
    a = str(row[0]).strip() if row[0] else ""
    b = str(row[1]).strip() if row[1] else ""
    if a and a != "UNAFFECTED":
        cur_sdv = a
    if b.startswith("Config"):
        cfg = {"label": b, "speed_cols": None, "row_param": None, "col_param": None,
               "grid": []}
        j = i + 1
        while j < min(i + 35, len(g)):
            r2 = g[j]
            b2 = str(r2[1]).strip() if r2[1] else ""
            h2 = str(r2[7]).strip() if r2[7] else ""
            i2 = str(r2[8]).strip() if r2[8] else ""
            if h2.startswith("Veh. Speed"):
                cfg["speed_cols"] = [v for v in r2[9:] if v is not None]
                cfg["col_param"] = "Vehicle Speed"
            if i2 and re.match(r"^[\d.]+-[\d.]+$", i2):
                vals = [v for v in r2[9:9 + len(cfg["speed_cols"] or [])]]
                cfg["grid"].append({"band": i2, "priorities": vals})
            elif i2 and not re.match(r"^[\d.]+-", i2) and cfg["row_param"] is None and i2 != "":
                cfg["row_param"] = i2
            if b2 == "Référence Ligne":
                r3 = g[j + 1]
                cfg["ref_ligne"] = str(r3[1]).strip() if r3[1] else None
                cfg["ref_colonne"] = str(r3[3]).strip() if r3[3] else None
                break
            j += 1
        if cur_sdv:
            prior.setdefault(cur_sdv, []).append(cfg)
        i = j
    i += 1
save("priorisation.json", prior)

# ------------------------------------------------------------ 10. TARGET VEHICLE
ws = wb["TARGET VEHICLE"]
tv = {"rows": []}
for row in rows_of(ws, max_c=6)[1:]:
    if not row[0]:
        continue
    tv["rows"].append({"sdv": str(row[0]).strip(), "drive_version": row[1],
                       "vehicle": row[2], "mode": row[3],
                       "driv": row[4] if isinstance(row[4], (int, float)) else None,
                       "dyn": row[5] if isinstance(row[5], (int, float)) else None})
save("target_vehicle.json", tv)

# ------------------------------------------------------------ 11. PARAMETRES GRAPH
ws = wb["PARAMETRES GRAPH"]
g = rows_of(ws, max_c=10)
charts = {}
cur_sdv = None
i = 0
while i < len(g):
    row = g[i]
    a = str(row[0]).strip() if row[0] else ""
    b = str(row[1]).strip() if row[1] else ""
    if a:
        cur_sdv = a
        charts[cur_sdv] = []
    if b.startswith("Graphique") and cur_sdv:
        active = any(str(v).strip() == "Activè" for v in row if v)
        try:
            xy = g[i + 2]
            yax = g[i + 4]
            xax = g[i + 6]
            charts[cur_sdv].append({
                "name": b, "active": active,
                "x": str(xy[1]).strip() if xy[1] else None,
                "y": str(xy[2]).strip() if xy[2] else None,
                "anchor": str(xy[3]).strip() if xy[3] else None,
                "y_min": yax[1], "y_max": yax[2], "y_step": yax[3],
                "x_min": xax[1], "x_max": xax[2], "x_step": xax[3]})
        except IndexError:
            pass
        i += 6
    i += 1
save("chart_params.json", charts)

# ------------------------------------------------------------ 12. CONFIGURATIONS lists
ws = wb["CONFIGURATIONS"]
lists = {
    "lever_positions": {"0": "P", "1": "R", "2": "N", "3": "D", "68": "M", "69": "S"},
    "versions": ["4.2", "4.6"],
    "target_vehicles": ["P8 MHEV MDL2"],
    "milestones": {str(ws.cell(row=r, column=1).value): ws.cell(row=r, column=2).value
                   for r in range(21, 35) if ws.cell(row=r, column=1).value},
    "areas": [str(ws.cell(row=r, column=1).value) for r in range(38, 44) if ws.cell(row=r, column=1).value],
    "engine_types": ["GASOLINE", "DIESEL"],
    "gearbox_types": ["AT"],
    "gears": ["5", "6", "7", "8", "9", "10"],
    "temperature_split": ws.cell(row=100, column=1).value,
    "modes": {}
}
for r in range(65, 86):
    code = ws.cell(row=r, column=1).value
    name = ws.cell(row=r, column=2).value
    fam = ws.cell(row=r, column=3).value
    if code is not None:
        lists["modes"][str(code)] = {"name": name, "family": fam}
save("configurations.json", lists)

# ------------------------------------------------------------ 13. UI layouts with styles


def color_of(c):
    try:
        rgb = c.fill.start_color.rgb
        if isinstance(rgb, str) and len(rgb) == 8 and rgb != "00000000":
            return "#" + rgb[2:]
    except Exception:
        pass
    return None


def font_of(c):
    f = c.font
    out = {}
    if f.bold:
        out["b"] = 1
    if f.size and f.size != 11:
        out["sz"] = f.size
    try:
        if f.color and f.color.rgb and isinstance(f.color.rgb, str) and f.color.rgb not in ("FF000000", "00000000"):
            out["c"] = "#" + f.color.rgb[2:]
    except Exception:
        pass
    if f.italic:
        out["i"] = 1
    return out or None


def extract_layout(sheet, max_r, max_c):
    ws = wb[sheet]
    cells = []
    for ri in range(1, max_r + 1):
        for ci in range(1, max_c + 1):
            c = ws.cell(row=ri, column=ci)
            v = c.value
            fill = color_of(c)
            font = font_of(c)
            has_border = any([c.border.left.style, c.border.right.style,
                              c.border.top.style, c.border.bottom.style])
            if v is None and not fill and not has_border:
                continue
            cell = {"r": ri, "c": ci}
            if v is not None:
                cell["v"] = v
            if fill:
                cell["f"] = fill
            if font:
                cell["ft"] = font
            if has_border:
                cell["bd"] = 1
            al = c.alignment
            if al and al.horizontal:
                cell["al"] = al.horizontal[0]
            cells.append(cell)
    merges = [str(m) for m in ws.merged_cells.ranges
              if m.min_row <= max_r and m.min_col <= max_c]
    widths = {}
    for col, dim in ws.column_dimensions.items():
        if dim.width:
            widths[col] = round(dim.width, 1)
    heights = {str(r): round(d.height, 1) for r, d in ws.row_dimensions.items()
               if d.height and r <= max_r}
    return {"cells": cells, "merges": merges, "widths": widths, "heights": heights,
            "max_r": max_r, "max_c": max_c}


save("layout_home.json", extract_layout("HOME", 34, 12))
save("layout_rating.json", extract_layout("RATING", 22, 26))
save("layout_vierge.json", extract_layout("VIERGE", 22, 91))
print("DONE")
