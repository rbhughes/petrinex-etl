from petrinex_etl.uwi import label_from_well_id, well_id_from_label


def test_docstring_example():
    assert well_id_from_label("00/07-19-010-15W4/0") == "100071901015W400"


def test_alphanumeric_location_exception():
    # AA/W0/F1-style exceptions are common; digits-only patterns drop them.
    assert well_id_from_label("AA/12-04-062-20W5/0") == "1AA120406220W500"
    assert well_id_from_label("W0/01-01-001-01W4/2") == "1W0010100101W402"


def test_event_sequence_is_trailing():
    # ES=3 must land in the last two chars, not where LE goes.
    assert well_id_from_label("02/07-19-010-15W4/3") == "102071901015W403"


def test_round_trip():
    for label in ("00/07-19-010-15W4/0", "AA/12-04-062-20W5/7"):
        well_id = well_id_from_label(label)
        assert well_id is not None
        assert label_from_well_id(well_id) == label


def test_rejects_garbage():
    assert well_id_from_label("not a uwi") is None
    assert label_from_well_id("ABWI0071901015W400") is None
