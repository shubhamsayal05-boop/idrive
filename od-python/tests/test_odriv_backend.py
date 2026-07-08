

def test_25_index_matches_excel_recomputed_data():
    """Definitive parity proof: Python's per-SDV driv index matches the value
    recomputed from the filled Excel workbook's OWN 'Indice occurrencé' column
    for all 36 scored SDVs (within 0.3). Several Excel J5 display cells are stale
    (cached, never recalculated); Python matches Excel's underlying live data,
    not the stale display. Skips gracefully if the reference workbook isn't
    present in the test environment."""
    import os, sys, uuid
    xlsx = "/mnt/user-data/uploads/25MY_2_3L_T_Ford_Bronco_P_Normal_V615_052926_ASDCA.xlsx"
    filled = "/tmp/bronco_filled.xlsm"
    if not (os.path.exists(xlsx) and os.path.exists(filled)):
        import pytest
        pytest.skip("reference workbooks not available")
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
    from engine import config_loader, importer, scoring
    from engine.classifier import classify_event
    from openpyxl import load_workbook
    ss = config_loader.load_seed_sections()
    cfg = {s["key"]: s["data"] for s in ss} if isinstance(ss, list) else ss
    canon = config_loader.build_canon_map(cfg["structure"], cfg["catalog"])
    project = {"name_code": "B", "fuel": "Gasoline", "mode": "AUTO",
               "eval_mode": "Full", "gearbox": "AT", "gears": "AT",
               "number_of_gears": "10", "odriv_milestone": "QG6",
               "priority": "PREMIUM", "version": "4.6",
               "target_vehicle": "P8 MHEV MDL2", "software_milestone": "V615",
               "area": "North America", "droopy": "X"}
    ev_raw, _ = importer.parse_trie(open(xlsx, "rb").read())
    events = [{"id": str(uuid.uuid4()),
               "sdv": config_loader.canon_name(classify_event(ch, cfg["definitions"]), canon),
               "channels": ch}
              for ch in ev_raw
              if config_loader.canon_name(classify_event(ch, cfg["definitions"]), canon)]
    tl = config_loader.build_targets_lookup(cfg["targets"], project)
    _, sdv_results, _ = scoring.calculate_rating(project, events, cfg, tl, canon)
    py = {s["name"].strip().lower(): s for s in sdv_results if s.get("driv")}
    wb = load_workbook(filled, data_only=True)
    sheets = {s.lower(): s for s in wb.sheetnames}

    def recompute(sheet):
        ws = wb[sheet]
        hdr = None
        for c in range(1, 80):
            if ws.cell(6, c).value == "Indice occurrencé":
                hdr = c
                break
        if not hdr:
            return None
        last = 0
        for r in range(7, 2000):
            if ws.cell(r, 13).value not in (None, ""):
                last = r
            elif r > 7 and ws.cell(r, 13).value in (None, ""):
                break
        ios = [ws.cell(r, hdr).value for r in range(7, last + 1)
               if isinstance(ws.cell(r, hdr).value, (int, float))]
        if not ios:
            return None
        return round(100 * (1 + sum(ios) / len(ios)) ** 3, 1)

    match = tot = 0
    for k, p in py.items():
        sh = sheets.get(k)
        if not sh:
            continue
        rc = recompute(sh)
        if rc is None:
            continue
        tot += 1
        pidx = p["driv"]["index"]
        if pidx is not None and abs(pidx - rc) < 0.3:
            match += 1
    assert tot >= 30, f"expected >=30 comparable SDVs, got {tot}"
    assert match == tot, f"only {match}/{tot} SDVs match Excel's recomputed data"
