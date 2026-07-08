"""Re-extract CONFIGURATIONS SEETINGS priority configs from the ODRIV
workbook, handling ALL grid layouts (not just throttle x speed).

Layouts observed:
  * 2D grid: row-param bands (col 8) x col-axis values (cols 9..N, header
    in the config's first row). e.g. Power-on upshift: Throttle bands x
    Veh.Speed columns.
  * 1D row list: row-param discrete values (Selector Lever P/R/N/D/M;
    Lever Old->Lever New transitions; Clim 0/1; band->single priority).
  * scalar: a single priority for the whole SDV (col 9 only).

Each config also carries condition gating (Engine type / Gearbox type /
Number of gears / Area, X-marked) used to pick the active config per
vehicle. Output schema (per SDV -> list of configs):
  {
    label, conditions:{engine:[..],gearbox:[..],gears:[..],area:[..]},
    col_param, col_values:[..],
    row_param, rows:[{key, band:[lo,hi]|None, priorities:[..]}],
    scalar: int|None
  }
"""
import json
import os
import re
import sys
from openpyxl import load_workbook

SRC = sys.argv[1] if len(sys.argv) > 1 else "source.xlsm"
OUT = sys.argv[2] if len(sys.argv) > 2 else \
    os.path.join(os.path.dirname(__file__), "data", "priorisation.json")

wb = load_workbook(SRC, read_only=True, data_only=True)
ws = wb["CONFIGURATIONS SEETINGS"]
rows = [list(r) for r in ws.iter_rows(min_row=1, max_row=ws.max_row,
                                      max_col=26, values_only=True)]

COND_LABELS = {"Engine type": "engine", "Gearbox type": "gearbox",
               "Number of gears": "gears", "Area": "area"}


def is_block_header(r):
    a = r[0]
    return (isinstance(a, str) and a.strip() and a.strip() == a.strip().upper()
            and len(a.strip()) > 2 and not a.strip().startswith("CONFIG")
            and r[1] is None)


def parse_band(s):
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)\s*$", str(s))
    if m:
        return [float(m.group(1)), float(m.group(2))]
    return None


# locate block boundaries
heads = [i for i, r in enumerate(rows) if is_block_header(r)]
heads.append(len(rows))

out = {}
for bi in range(len(heads) - 1):
    start, end = heads[bi], heads[bi + 1]
    name = rows[start][0].strip()
    configs = []
    i = start + 1
    while i < end:
        r = rows[i]
        if isinstance(r[1], str) and r[1].strip().lower().startswith("config"):
            cfg = {"label": r[1].strip(),
                   "conditions": {"engine": [], "gearbox": [],
                                  "gears": [], "area": []},
                   "col_param": None, "col_values": [],
                   "row_param": None, "rows": [], "scalar": None}
            j = i + 1
            row_param = None
            cur_cond = {1: None, 4: None}
            while j < end and not (isinstance(rows[j][1], str)
                                   and rows[j][1].strip().lower().startswith("config")):
                rr = rows[j]
                for c in (1, 4):
                    lab = rr[c]
                    if isinstance(lab, str) and lab.strip() in COND_LABELS:
                        cur_cond[c] = COND_LABELS[lab.strip()]
                if isinstance(rr[3], str) and rr[3].strip().upper() == "X" \
                        and rr[2] is not None and cur_cond[1]:
                    cfg["conditions"][cur_cond[1]].append(str(rr[2]).strip())
                if isinstance(rr[6], str) and rr[6].strip().upper() == "X" \
                        and rr[5] is not None and cur_cond[4]:
                    cfg["conditions"][cur_cond[4]].append(str(rr[5]).strip())
                # LEVER-TRANSITION layout: col7='Lever Old', col8='Lever New',
                # and the col-axis (speed) header is on a nearby row.
                if isinstance(rr[7], str) and rr[7].strip() == "Lever Old" \
                        and isinstance(rr[8], str) and rr[8].strip() == "Lever New":
                    cfg["row_param"] = "lever_transition"
                    # find the speed col-axis values from this or the prior row
                    if not cfg["col_values"]:
                        for back in (j - 1, j):
                            cand = [rows[back][c] for c in range(9, 26)
                                    if rows[back][c] is not None]
                            if cand and all(isinstance(v, (int, float)) for v in cand):
                                cfg["col_param"] = "Vehicle Speed"
                                cfg["col_values"] = cand
                                break
                    j += 1
                    continue
                if cfg["row_param"] == "lever_transition" \
                        and isinstance(rr[7], str) and isinstance(rr[8], str):
                    prios_lt = [rr[c] for c in range(9, 26) if rr[c] is not None]
                    if prios_lt and all(isinstance(p, (int, float)) for p in prios_lt):
                        cfg["rows"].append({
                            "key": f"{rr[7].strip()}->{rr[8].strip()}",
                            "old": rr[7].strip(), "new": rr[8].strip(),
                            "band": None,
                            "priorities": [int(p) for p in prios_lt]})
                    j += 1
                    continue
                # COLUMN-axis header: col 7 = param name, cols 9.. = numeric values
                hdr7 = rr[7] if isinstance(rr[7], str) else None
                vals9 = [rr[c] for c in range(9, 26) if rr[c] is not None]
                if hdr7 and hdr7.strip() not in ("X",) and hdr7.strip() not in COND_LABELS \
                        and vals9 and all(isinstance(v, (int, float)) for v in vals9) \
                        and not cfg["col_param"]:
                    cfg["col_param"] = hdr7.strip()
                    cfg["col_values"] = vals9
                    j += 1
                    continue
                # single-axis row-param header at col 7 (no numeric values)
                if hdr7 and hdr7.strip() not in ("X",) and hdr7.strip() not in COND_LABELS \
                        and not vals9 and row_param is None:
                    row_param = hdr7.strip()
                # ROW-axis param label at col 8 (text, no priorities)
                key = rr[8]
                prios = [rr[c] for c in range(9, 26) if rr[c] is not None]
                if isinstance(key, str) and not prios:
                    if row_param is None:
                        row_param = key.strip()
                    key = None
                if key is not None and prios and all(
                        isinstance(p, (int, float)) for p in prios):
                    cfg["rows"].append({"key": str(key).strip(),
                                        "band": parse_band(key),
                                        "priorities": [int(p) for p in prios]})
                elif key is None and prios and cfg["col_param"] \
                        and all(isinstance(p, (int, float)) for p in prios) \
                        and not cfg["rows"]:
                    # single implicit row spanning the column axis
                    cfg["rows"].append({"key": "*", "band": None,
                                        "priorities": [int(p) for p in prios]})
                elif key is None and len(prios) == 1 \
                        and isinstance(prios[0], (int, float)) and not cfg["rows"]:
                    cfg["scalar"] = int(prios[0])
                j += 1
            if row_param:
                cfg["row_param"] = row_param
            configs.append(cfg)
            i = j
        else:
            i += 1
    if configs:
        out[name] = configs

# map workbook param names -> event channel names
PARAM_CHANNEL = {
    "Throttle": "Throttle Position", "Throttle (%)": "Throttle Position",
    "Veh. Speed (km/h)": "Vehicle Speed", "Vehicle Speed": "Vehicle Speed",
    "Selector Lever": "selector lever start",
    "Lever New": "selector lever end",
    "Lever Old": "selector lever start",
    "Engine Temperature": "Engine Temperature", "Clim": "Clim",
}
for sdv, cfgs in out.items():
    for c in cfgs:
        c["col_channel"] = PARAM_CHANNEL.get(c.get("col_param"), c.get("col_param"))
        c["row_channel"] = PARAM_CHANNEL.get(c.get("row_param"), c.get("row_param"))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

# summary
layouts = {"2d": 0, "1d": 0, "scalar": 0, "empty": 0}
for sdv, cfgs in out.items():
    c = cfgs[0]
    if c["col_param"] and c["rows"]:
        layouts["2d"] += 1
    elif c["rows"]:
        layouts["1d"] += 1
    elif c["scalar"] is not None:
        layouts["scalar"] += 1
    else:
        layouts["empty"] += 1
print(f"extracted {len(out)} SDV priority configs")
print("layouts:", layouts)


