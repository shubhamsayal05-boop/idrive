"""Event classification engine — assigns each recorded event to its SDV.

Rule semantics:
- Rules evaluated in ORDRE; first fully-matching active rule wins.
- VALEUR ';'-separated list = OR across the list; literal VIDE = empty string.
- Rows sharing a group number are OR'd; different groups are AND'd.
- Missing channel ("FFF" sentinel) -> the condition auto-passes.
"""

MISSING = "__FFF__"

POSITIVE_OPS = {"CONTIENT", "EGAL A", "INFERIEUR A", "INFERIEUR OU EGAL A",
                "SUPERIEUR A", "SUPERIEUR OU EGAL A"}
NEGATIVE_OPS = {"NE CONTIENT PAS", "DIFFERENT DE"}


def _to_float(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _check_single(value, op, target):
    sval = "" if value is None else str(value).strip().lower()
    starget = str(target).strip().lower()
    if starget == "vide":
        starget = ""
    if op == "CONTIENT":
        return starget in sval if starget else sval == ""
    if op == "NE CONTIENT PAS":
        return starget not in sval if starget else sval != ""
    if op == "EGAL A":
        return sval == starget
    if op == "DIFFERENT DE":
        return sval != starget
    fv, ft = _to_float(value), _to_float(target)
    if fv is None or ft is None:
        return False
    if op == "INFERIEUR A":
        return fv < ft
    if op == "INFERIEUR OU EGAL A":
        return fv <= ft
    if op == "SUPERIEUR A":
        return fv > ft
    if op == "SUPERIEUR OU EGAL A":
        return fv >= ft
    return False


def check_condition(value, op, target):
    """OR across ';'-list for positive ops, AND for negative ops."""
    if value == MISSING:
        return True  # missing-channel auto-pass
    parts = [p.strip() for p in str(target).split(";") if p.strip() != ""]
    if not parts:
        parts = [""]
    if op in NEGATIVE_OPS:
        return all(_check_single(value, op, p) for p in parts)
    return any(_check_single(value, op, p) for p in parts)


def _norm(s):
    return str(s).replace("\u00b7", ".").strip().lower()


CHANNEL_ALIASES = {
    "throttle position": ["throttle position", "max throttle position",
                          "pedal", "pedal_act"],
    "throttle": ["throttle position", "max throttle position",
                 "pedal", "pedal_act"],
    "vehicle speed": ["vehicle speed", "veh speed", "vehicle speed start"],
    "accelerationchassis": ["ax mean", "deceleration level", "ax"],
    "engine temperature": ["engine temperature", "engine temp",
                            "coolant temperature", "gearbox temperature",
                            "oil temperature"],
    "clim": ["clim", "ac status", "air conditioning"],
    "selector lever start": ["selector lever start", "lever start",
                             "old selector_lever_position",
                             "old selector lever position",
                             "old selector lever",
                             "selector_lever_position",
                             "selector lever position", "selector lever"],
    "selector lever end": ["selector lever end", "lever end",
                           "new selector_lever_position",
                           "new selector lever position",
                           "new selector lever"],
    "selector lever": ["selector_lever_position", "selector lever position",
                       "selector lever"],
}
# aliases requiring an EXACT channel match (no startswith), to avoid grabbing
# similarly-named rating criteria like "Pedal map" or "Pedal hysteresis".
_EXACT_ALIASES = {"pedal", "pedal_act", "vehicle speed", "clim",
                  "throttle position", "max throttle position",
                  "selector lever start", "selector lever end",
                  "old selector_lever_position", "new selector_lever_position",
                  "old selector lever position", "new selector lever position",
                  "selector_lever_position", "selector lever position",
                  "ax mean", "deceleration level"}


def get_channel(channels, name):
    """Resolve a semantic channel name against 'Family, Channel' keys."""
    if name in channels:
        return channels[name]
    lname = _norm(name)
    for key, val in channels.items():
        k = _norm(key)
        if k == lname:
            return val
        if "," in k and k.split(",", 1)[1].strip() == lname:
            return val
    # also allow matching just the channel part of the requested name
    if "," in lname:
        part = lname.split(",", 1)[1].strip()
        for key, val in channels.items():
            k = _norm(key)
            if k == part or ("," in k and k.split(",", 1)[1].strip() == part):
                return val
    for alias in CHANNEL_ALIASES.get(lname, []):
        exact = alias in _EXACT_ALIASES
        for key, val in channels.items():
            k = _norm(key)
            kc = k.split(",", 1)[1].strip() if "," in k else k
            if kc == alias or (not exact and kc.startswith(alias)):
                return val
    return MISSING


def classify_event(channels, rules):
    """Return the SDV name of the first fully-matching rule, or ''. """
    for rule in sorted(rules, key=lambda r: r.get("order", 0)):
        if not rule.get("active", True):
            continue
        groups = {}
        for cond in rule.get("conditions", []):
            groups.setdefault(cond.get("group", 1), []).append(cond)
        matched = True
        for _, conds in sorted(groups.items()):
            # within group: OR (findV latches a hit)
            group_ok = False
            for cond in conds:
                col = cond.get("column", "")
                # resolve the full "Family, Channel" key first, then channel part
                value = get_channel(channels, col)
                if value == MISSING and "," in col:
                    value = get_channel(channels, col.split(",", 1)[1].strip())
                if check_condition(value, cond.get("op", "CONTIENT"), cond.get("value", "")):
                    group_ok = True
                    break
            if not group_ok:
                matched = False
                break
        if matched and rule.get("conditions"):
            return rule["sdv"]
    return ""
