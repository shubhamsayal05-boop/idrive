"""Normalize PRE REMPLISSAGE report form fields (all optional)."""
from datetime import datetime


def _clean(v):
    if v is None:
        return ""
    return str(v).strip()


def normalize_report_fields(project, fields):
    """Map Excel Preremplissage form values to report bookmarks.

    Every field is optional — empty values fall back to project data or 'n/a'.
    """
    p = project or {}
    f = fields or {}
    project_name = _clean(f.get("project")) or _clean(p.get("name_code")) or "n/a"
    site = _clean(f.get("site"))
    name = _clean(f.get("name")) or _clean(f.get("sender_name"))
    return {
        "project": project_name,
        "car_number": _clean(f.get("car_number")) or project_name,
        "domain": _clean(f.get("domain")) or "DRIVABILITY-DYNAMISM",
        "standard": _clean(f.get("standard")) or "n/a",
        "stage": _clean(f.get("stage")) or "n/a",
        "goal": _clean(f.get("goal")) or "n/a",
        "site": site or "n/a",
        "loc_date_test": _clean(f.get("loc_date_test")) or "n/a",
        "climate": _clean(f.get("climate")) or "n/a",
        "ac_status": _clean(f.get("ac_status")) or "n/a",
        "vehicle_mileage": _clean(f.get("vehicle_mileage")) or "n/a",
        "vehicle_options": _clean(f.get("vehicle_options")) or "n/a",
        "name": name or "n/a",
        "sender_name": name or _clean(f.get("from")) or "n/a",
        "sender_dept": _clean(f.get("sender_dept")) or _clean(f.get("department")) or "n/a",
        "from": _clean(f.get("from")) or name or "n/a",
        "sender_tel": _clean(f.get("sender_tel")) or _clean(f.get("telephone")) or "n/a",
        "sender_email": _clean(f.get("sender_email")) or _clean(f.get("email")) or "n/a",
        "synthesis": _clean(f.get("synthesis")),
        "dynamism_synthesis": _clean(f.get("dynamism_synthesis")),
        "recipients": _clean(f.get("recipients")) or "For Information",
        "places": "%s %s" % (site or "Place, n/a", datetime.now().strftime("%m/%d/%Y")),
    }


def default_doc_versions(project):
    """Build DocVersions rows from project when the form leaves them empty."""
    p = project or {}
    version = _clean(p.get("version")) or "n/a"
    sw = _clean(p.get("software_milestone")) or version
    cal = _clean(p.get("calibration")) or version
    return [
        {"name": "self-learning tool", "version": ""},
        {"name": "Event collector", "version": ""},
        {"name": "Objective evaluation", "version": sw},
        {"name": "Experiment", "version": ""},
        {"name": "ODRIV", "version": "VERSION %s" % version if version != "n/a" else ""},
    ]
