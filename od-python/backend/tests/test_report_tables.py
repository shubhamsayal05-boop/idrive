"""Unit tests for shared report table helpers."""
from engine.report_tables import _priority_table_png


def test_priority_table_png_dict_channels():
    """Events from Access import store channels as header->value dicts."""
    events = [
        {
            "channels": {"Sub Event Name": "Creep launch A", "Throttle Position": 12.5},
            "driv": {"criticity": 1, "priority": 1, "color": "RED", "indice_occ": -1.2},
        },
        {
            "channels": {"Sub Event Name": "Creep launch B"},
            "driv": {"criticity": 3, "priority": 2, "color": "GREEN", "indice_occ": 0.5},
        },
    ]
    hi = _priority_table_png(events, "driv", "high")
    lo = _priority_table_png(events, "driv", "low")
    assert hi is not None
    assert lo is not None
    assert hi.getvalue()
    assert lo.getvalue()
