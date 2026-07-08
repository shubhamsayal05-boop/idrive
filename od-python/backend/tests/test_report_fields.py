"""Tests for PRE REMPLISSAGE field normalization."""
from engine.report_fields import default_doc_versions, normalize_report_fields


def test_empty_fields_use_defaults():
    project = {"name_code": "ford", "version": "4.6"}
    f = normalize_report_fields(project, {})
    assert f["project"] == "ford"
    assert f["standard"] == "n/a"
    assert f["name"] == "n/a"
    assert f["sender_email"] == "n/a"


def test_partial_fields_allowed():
    project = {"name_code": "ford"}
    f = normalize_report_fields(project, {"name": "John Doe", "telephone": "123"})
    assert f["name"] == "John Doe"
    assert f["sender_tel"] == "123"
    assert f["climate"] == "n/a"


def test_default_doc_versions_from_project():
    dv = default_doc_versions({"name_code": "ford", "version": "4.6", "software_milestone": "QG6"})
    assert dv[-1]["name"] == "ODRIV"
    assert "4.6" in dv[-1]["version"]
