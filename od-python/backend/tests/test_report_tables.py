"""Unit tests for shared report table helpers."""
from engine.report_tables import _crit_rank, _priority_table_png, _scorecard_png, part_label


def test_part_label_uses_dynamism():
    assert part_label("dyn") == "DYNAMISM"
    assert part_label("driv") == "DRIVABILITY"


def test_crit_rank_string_levels():
    assert _crit_rank("Red +") < _crit_rank("Green")
    assert _crit_rank("Red") < _crit_rank("Yellow")


def test_priority_table_png_dict_channels():
    """Events from Access import store channels as header->value dicts."""
    events = [
        {
            "channels": {"Sub Event Name": "Creep launch A", "Throttle Position": 12.5},
            "driv": {"criticity": "Red +", "priority": 1, "color": "RED", "indice_occ": -1.2},
        },
        {
            "channels": {"Sub Event Name": "Creep launch B"},
            "driv": {"criticity": "Green", "priority": 2, "color": "GREEN", "indice_occ": 0.5},
        },
    ]
    hi = _priority_table_png(events, "driv", "high")
    lo = _priority_table_png(events, "driv", "low")
    assert hi is not None
    assert lo is not None
    assert hi.getvalue()
    assert lo.getvalue()


def test_scorecard_with_groups():
    data = {
        "catalog_groups": [{"name": "Drive away", "sdvs": ["SDV A"]}],
        "sdv_results": [{
            "name": "SDV A",
            "driv": {"index": 70, "status": {"1": "RED", "2": "GREEN", "3": "GREEN"},
                     "lowest_event": "E1"},
            "dyn": {"index": 80, "status": {"1": "GREEN", "2": "GREEN", "3": "GREEN"},
                    "lowest_event": "-"},
        }],
    }
    png = _scorecard_png(data)
    assert png is not None
    assert png.getvalue()
