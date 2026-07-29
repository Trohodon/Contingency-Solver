from contingency_solver.powerworld.simauto_client import records_from_response


def test_records_from_response_maps_rows_to_fields() -> None:
    rows = ((1, "A"), (2, "B"))
    assert records_from_response(["BusNum", "BusName"], (rows,)) == [
        {"BusNum": 1, "BusName": "A"},
        {"BusNum": 2, "BusName": "B"},
    ]


def test_records_from_response_accepts_nested_rows() -> None:
    rows = (((1, "A"),), ((2, "B"),))
    assert records_from_response(["BusNum", "BusName"], (rows,))[1]["BusName"] == "B"
