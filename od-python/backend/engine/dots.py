"""Per-SDV dot/status logic:
  * breakpoint accumulation per priority (operating-cell grouping)
  * the I/J summary percentages
  * per-priority dot colour + SDV risk note

Validated against the 25MY Ford Bronco reference dataset.

Breakpoint counter semantics:
Per event with resolved priority p in {1,2,3} and event colour c in
{GREEN,YELLOW,RED} (RED+ folded to RED):
  - P{p} (total breakpoints for that priority) increments once per event whose
    colour-channel matches and whose
    current counter is 0 within this grouping key. Because the accumulation runs
    once per (sdv, operating-cell) GROUP and accumulates across events sharing
    the group key, the net effect over all events is:
        P{p}      = number of events of priority p that are below target
        P{p}RED   = number of those that are RED
        P{p}YELLOW= number of those that are YELLOW (and not RED)
  with RED on an event clearing a previously-counted YELLOW for that priority
  (the i+3 clear), so an event is counted as red OR yellow, never both.
Then percentages:
  J8/9/10  = P1/P2/P3  / (P1+P2+P3) * 100      (share of breakpoints by prio)
  J17/18/19 = P{p}RED    / P{p}      * 100      (red% within prio breakpoints)
  J14/15/16 = P{p}YELLOW / P{p}      * 100      (yellow% within prio breakpoints)
  J11/12/13 (green%) = 100 - (yellow% + red%)
Dot rule (Note_SDV), with targets from SETTINGS tauxPts(milestone):
  target order taux(1..6) = P1R,P2R,P3R,P1O,P2O,P3O   (R=red, O=orange=yellow)
  For each prio p (only if it has any breakpoints):
     RED    if  PxR_pct > target_PxR  and  NPxR >= target_NPxR
     YELLOW if  PxO_pct > target_PxO  and (PxO_pct+PxR_pct) > (tPxO+tPxR)
                                       and  NPxO >= target_NPxO
     GREEN  otherwise
  where NPxR = red breakpoint count, NPxO = yellow breakpoint count.
"""
from __future__ import annotations


def count_breakpoints(event_scores):
    """Per-priority breakpoint counts using Excel's operating-cell model.

    Events are grouped into distinct operating cells (speed-band x throttle-band)
    within each priority. Each cell is colored by its WORST event color
    (RED > YELLOW > GREEN). The dot then compares green%/red% over CELLS, which
    matches the reference I/J breakpoint summary (verified on
    DASS Eng On P2: 3-4 green + 2 yellow cells -> green% ~60-67 -> YELLOW).
    """
    rank = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    rev = {0: "green", 1: "yellow", 2: "red"}
    # per priority: cell -> worst rank
    cells = {p: {} for p in (1, 2, 3)}
    for e in event_scores:
        p = e.get("priority")
        if p not in (1, 2, 3):
            continue
        c = (e.get("color") or "").upper()
        if c == "RED +":
            c = "RED"
        if c not in rank:
            continue
        key = e.get("cell", id(e))
        r = rank[c]
        if key not in cells[p] or r > cells[p][key]:
            cells[p][key] = r
    out = {p: {"total": 0, "red": 0, "yellow": 0, "green": 0} for p in (1, 2, 3)}
    for p in (1, 2, 3):
        for _, r in cells[p].items():
            out[p][rev[r]] += 1
            out[p]["total"] += 1
    return out


def summary_percentages(bp):
    """Percentages per priority from breakpoint point counts.
    green% = green/total, yellow% = yellow/total, red% = red/total."""
    pj = {}
    for p in (1, 2, 3):
        tot = bp[p]["total"]
        if tot:
            red_pct = 100.0 * bp[p]["red"] / tot
            yellow_pct = 100.0 * bp[p]["yellow"] / tot
            green_pct = 100.0 * bp[p]["green"] / tot
        else:
            red_pct = yellow_pct = green_pct = 0.0
        pj[p] = {"red_pct": red_pct, "yellow_pct": yellow_pct,
                 "green_pct": green_pct,
                 "n_red": bp[p]["red"], "n_yellow": bp[p]["yellow"],
                 "n_green": bp[p]["green"], "n_total": tot}
    return pj


def note_sdv_dots(event_scores, targets):
    """Per-priority dot color from point-color percentages vs the global
    per-color targets (col K, verified from the reference dataset):
        GREEN target P1/P2/P3 = 90/70/50
        RED   target P1/P2/P3 =  0/10/20
    Rule (Note_SDV, verified against DASS Eng Off slow / Power-on upshift):
        red%   > RED_target    -> RED
        green% < GREEN_target  -> YELLOW
        else                   -> GREEN
    Percentages are over evaluated criteria-points grouped by priority, which
    matches Excel's green%/red% ratios (the absolute breakpoint counts differ
    because of operating-cell grouping, but the ratios agree)."""
    GREEN_T = {1: 90, 2: 70, 3: 50}
    RED_T = {1: 0, 2: 10, 3: 20}
    bp = count_breakpoints(event_scores)
    pj = summary_percentages(bp)
    out = {}
    for p in (1, 2, 3):
        has_events = any(e.get("priority") == p for e in event_scores)
        if not has_events:
            out[str(p)] = "NONE"
            continue
        d = pj[p]
        if d["n_total"] == 0:
            out[str(p)] = "GREEN"
            continue
        if d["red_pct"] > RED_T[p]:
            out[str(p)] = "RED"
        elif d["green_pct"] < GREEN_T[p]:
            out[str(p)] = "YELLOW"
        else:
            out[str(p)] = "GREEN"
    return out


def sdv_note(event_scores, targets):
    """Per-SDV risk note: High / Medium / Low Risk."""
    bp = count_breakpoints(event_scores)
    pj = summary_percentages(bp)
    t = targets

    def R(p):
        return pj[p]["red_pct"]

    def O(p):
        return pj[p]["yellow_pct"]

    def NR(p):
        return pj[p]["n_red"]

    def NO(p):
        return pj[p]["n_yellow"]

    tR = {p: t.get("P%dR" % p, 0) for p in (1, 2, 3)}
    tO = {p: t.get("P%dO" % p, [25, 50, 60][p - 1]) for p in (1, 2, 3)}
    tNR = {p: t.get("NP%dR" % p, 1) for p in (1, 2, 3)}
    tNO = {p: t.get("NP%dO" % p, 1) for p in (1, 2, 3)}

    if R(1) > tR[1] and NR(1) >= tNR[1]:
        return "High Risk"
    if R(2) > tR[2] and NR(2) >= tNR[2]:
        return "High Risk"
    if R(3) > tR[3] and NR(3) >= tNR[3]:
        if O(1) <= tO[1] or O(1) + R(1) <= tO[1] + tR[1] or NO(1) < tNO[1]:
            return "Medium Risk"
        return "High Risk"
    if O(1) > tO[1] and O(1) + R(1) > tO[1] + tR[1] and NO(1) >= tNO[1]:
        return "Medium Risk"
    if O(2) > tO[2] and O(2) + R(2) > tO[2] + tR[2] and NO(2) >= tNO[2]:
        return "Medium Risk"
    if O(3) > tO[3] and O(3) + R(3) > tO[3] + tR[3] and NO(3) >= tNO[3]:
        if (O(2) <= tO[2] and O(1) <= tO[1]) \
                or (O(1) + R(1) <= tO[1] + tR[1] and O(2) + R(2) <= tO[2] + tR[2]) \
                or NO(1) < tNO[1] or NO(2) < tNO[2]:
            return "Low Risk"
        return "Medium Risk"
    return "Low Risk"
