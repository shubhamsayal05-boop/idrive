"""Per-event colour logic.

Each criterion cell is assigned to one of 6 bands relative to its
(waterline, target) pair, tallied into red/yellow/green/white counters
indexed by the criterion's criticity tier (1 = critical/C1, 2 =
secondary/C2, 3 = excluded). The event's final colour is then a
C1-gated, C2-majority cascade.

Verified against the 25MY Ford Bronco reference dataset.
"""
from __future__ import annotations
import struct


def _s(x):
    """Round a Python float to IEEE-754 single precision.
    The band boundaries are computed in single precision, and on exact
    boundaries single vs double precision can disagree (flipping the deepest-red
    band and therefore the RED+ flag), so we must replicate CSng exactly."""
    return struct.unpack("f", struct.pack("f", x))[0]


def classify_band(val, waterline, target, criticity, tally):
    """Bin one criterion value into a colour band and increment the tally.

    tally is a dict of 4 lists indexed by criticity tier 1..3:
        tally['r'][c], tally['y'][c], tally['g'][c], tally['w'][c]
    Bands (span = target - waterline):
        val <  wl - span                          -> red   (deep)
        wl - span <= val < wl                      -> red
        wl <= val < wl + span/3                     -> yellow
        wl + span/3 <= val < wl + 2*span/3          -> yellow
        wl + 2*span/3 <= val < target              -> yellow
        val >= target                              -> green
        non-numeric / missing                      -> white
    """
    c = int(criticity)
    if c not in (1, 2, 3):
        c = 2
    if val is None:
        tally["w"][c] += 1
        return
    try:
        v = float(val)
    except (TypeError, ValueError):
        tally["w"][c] += 1
        return
    # Boundaries are compared in 32-bit single precision: waterline and
    # target come from cells as Single, and textVal is CSng(...). On exact band
    # boundaries (e.g. val == waterline-(target-waterline)) single vs double
    # precision can disagree, which flips the deepest-red band and therefore the
    # RED+ flag. Replicate CSng so the band edges match Excel bit-for-bit.
    v32 = _s(v)
    wl32 = _s(waterline)
    t32 = _s(target)
    span32 = _s(t32 - wl32)
    b_deep = _s(wl32 - span32)                 # 222;0;0 boundary
    b_red = wl32                               # 246;110;96 .. wl
    b_y1 = _s(wl32 + _s(span32 / _s(3.0)))
    b_y2 = _s(wl32 + _s(_s(_s(2.0) * span32) / _s(3.0)))
    if v32 < b_deep:
        tally["r"][c] += 1
        tally["deep_red"][c] += 1            # 222;0;0 band -> RED+ trigger
    elif v32 < b_red:                          # wl-span <= v < wl
        tally["r"][c] += 1
    elif v32 < b_y1:                           # wl <= v < wl+span/3
        tally["y"][c] += 1
    elif v32 < b_y2:
        tally["y"][c] += 1
    elif v32 < t32:
        tally["y"][c] += 1
    else:                                      # v >= target
        tally["g"][c] += 1


def affect_color(tally) -> str:
    """Event colour: a C1-gated, C2-majority cascade -> RED/YELLOW/GREEN."""
    pr, py, pg, pw = tally["r"], tally["y"], tally["g"], tally["w"]
    c2_total = pr[2] + py[2] + pg[2] + pw[2]
    c2_rated = pr[2] + py[2] + pg[2]

    if pr[1] >= 1:
        return "RED"

    if pr[1] == 0 and py[1] >= 1:
        if c2_total > 2:
            if pr[2] >= 0.5 * c2_total and c2_total > 0:
                return "RED"
            return "YELLOW"
        if c2_rated == 2:
            return "RED" if pr[2] == 2 else "YELLOW"
        if c2_rated == 1:
            return "RED" if pr[2] == 1 else "YELLOW"
        return "YELLOW"                        # c2_rated == 0

    if pr[1] == 0 and py[1] == 0:
        if c2_total > 2:
            if pr[2] >= 0.5 * c2_total and c2_total > 0:
                return "RED"
            if pr[2] < 0.5 * c2_total and c2_total > 0:
                if py[2] + pr[2] >= 0.5 * c2_total:
                    return "YELLOW"
                return "GREEN"
            return "GREEN"
        if c2_rated == 2:
            if pr[2] == 2:
                return "RED"
            if (pr[2] == 1 and py[2] == 1) or py[2] == 2:
                return "YELLOW"
            return "GREEN"
        if c2_rated == 1:
            return "YELLOW" if (pr[2] + py[2] == 1) else "GREEN"
        return "GREEN"                          # c2_rated == 0

    return "GREEN"


def new_tally():
    return {k: [0, 0, 0, 0] for k in ("r", "y", "g", "w", "deep_red")}
