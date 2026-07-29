from typing import Any

import pytest

from contingency_solver.powerworld import PowerWorldReader, PowerWorldSchema, SchemaResolutionError, records_from_response


class FakeClient:
    def __init__(self) -> None:
        self.available = {
            "Bus": {"BusNum", "BusName", "BusNomVolt", "Latitude", "Longitude", "Status"},
            "Branch": {"BusNum", "BusNum:1", "LineCircuit", "Status"},
            "Contingency": {"CTGLabel", "Category", "Skip", "Solved", "NumActions"},
        }
        self.rows = {
            "Bus": [{"BusNum": "101", "BusName": "A", "BusNomVolt": "115", "Latitude": "40", "Longitude": "-82", "Status": "Closed"}],
            "Branch": [{"BusNum": "101", "BusNum:1": "102", "LineCircuit": "1", "Status": "Closed"}],
            "Contingency": [{"CTGLabel": "CTG_A", "Category": "Thermal", "Skip": "No", "Solved": "Yes", "NumActions": "1"}],
        }

    def get_field_list(self, object_type: str) -> set[str]:
        return self.available[object_type]

    def get_rows(self, object_type: str, fields: list[str]) -> list[dict[str, Any]]:
        return [{field: row[field] for field in fields} for row in self.rows[object_type]]


def schema() -> PowerWorldSchema:
    return PowerWorldSchema(
        {
            "objects": {
                "bus": {
                    "object_type": "Bus",
                    "fields": {
                        "number": ["BusNum"],
                        "name": ["BusName"],
                        "nominal_kv": ["BusNomVolt"],
                        "latitude": ["Latitude"],
                        "longitude": ["Longitude"],
                        "status": ["Status"],
                        "area": ["AreaNum"],
                        "zone": ["ZoneNum"],
                        "owner": ["OwnerNum"],
                        "substation": ["SubName"],
                    },
                },
                "branch": {
                    "object_type": "Branch",
                    "fields": {
                        "from_bus": ["BusNum"],
                        "to_bus": ["BusNum:1"],
                        "circuit": ["LineCircuit"],
                        "status": ["Status"],
                        "nominal_kv": ["NomkV"],
                    },
                },
                "contingency": {
                    "object_type": "Contingency",
                    "fields": {
                        "name": ["CTGLabel"],
                        "category": ["Category"],
                        "skip": ["Skip"],
                        "solved": ["Solved"],
                        "action_count": ["NumActions"],
                    },
                },
            }
        }
    )


def test_schema_resolution() -> None:
    assert schema().resolve_field("bus", "number", {"busnum"}) == "busnum"
    with pytest.raises(SchemaResolutionError):
        schema().resolve_field("bus", "latitude", {"Lat"})


def test_records_from_response() -> None:
    assert records_from_response(["BusNum", "BusName"], (((1, "A"), (2, "B")),))[1]["BusName"] == "B"


def test_reader_maps_powerworld_rows() -> None:
    reader = PowerWorldReader(FakeClient(), schema())  # type: ignore[arg-type]
    assert reader.read_buses()[0].number == 101
    assert reader.read_branches()[0].pair == (101, 102)
    assert reader.read_contingencies()[0].name == "CTG_A"
