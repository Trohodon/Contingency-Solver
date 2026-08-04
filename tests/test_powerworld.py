from typing import Any
from pathlib import Path

import pytest

from contingency_solver.core import CandidateLine, ConductorModel, calculate_line_parameters
from contingency_solver.powerworld import (
    PowerWorldReader,
    PowerWorldSchema,
    SchemaResolutionError,
    build_candidate_branch_aux,
    records_from_powerworld_csv,
    records_from_response,
)


class FakeClient:
    def __init__(self) -> None:
        self.available = {
            "Bus": {"BusNum", "BusName", "BusNomVolt", "Latitude", "Longitude", "Status"},
            "Branch": {"BusNum", "BusNum:1", "LineCircuit", "Status"},
            "Contingency": {"CTGLabel", "Category", "Skip", "Solved", "NumActions"},
            "ViolationCTG": {"CTGLabel", "LimViolID", "LimViolLimit", "LimViolValue", "LimViolPct", "LimViolCalc"},
        }
        self.rows = {
            "Bus": [{"BusNum": "101", "BusName": "A", "BusNomVolt": "115", "Latitude": "40", "Longitude": "-82", "Status": "Closed"}],
            "Branch": [{"BusNum": "101", "BusNum:1": "102", "LineCircuit": "1", "Status": "Closed"}],
            "Contingency": [{"CTGLabel": "CTG_A", "Category": "Thermal", "Skip": "No", "Solved": "Yes", "NumActions": "1"}],
            "ViolationCTG": [
                {
                    "CTGLabel": "CTG_A",
                    "LimViolID": "Line 101-102 1",
                    "LimViolLimit": "100",
                    "LimViolValue": "125",
                    "LimViolPct": "125%",
                    "LimViolCalc": "Limit Monitoring",
                },
                {
                    "CTGLabel": "CTG_B",
                    "LimViolID": "Bus 55 low voltage",
                    "LimViolLimit": "0.95",
                    "LimViolValue": "0.92",
                    "LimViolPct": "130",
                    "LimViolCalc": "Voltage",
                },
            ],
        }

    def get_field_list(self, object_type: str) -> set[str]:
        return self.available[object_type]

    def get_rows(self, object_type: str, fields: list[str], filter_name: str = "") -> list[dict[str, Any]]:
        return [{field: row[field] for field in fields} for row in self.rows[object_type]]

    def run_script_command(self, command: str) -> None:
        return None


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
                "violation_ctg": {
                    "object_type": "ViolationCTG",
                    "fields": {
                        "contingency": ["CTGLabel"],
                        "violation_id": ["LimViolID"],
                        "limit": ["LimViolLimit"],
                        "value": ["LimViolValue"],
                        "percent": ["LimViolPct"],
                        "category": ["LimViolCat"],
                    },
                },
            },
            "script_commands": {"load_aux": "LoadAux(\"{aux_path}\")"},
        }
    )


def test_schema_resolution() -> None:
    assert schema().resolve_field("bus", "number", {"busnum"}) == "busnum"
    with pytest.raises(SchemaResolutionError):
        schema().resolve_field("bus", "latitude", {"Lat"})


def test_records_from_response() -> None:
    assert records_from_response(["BusNum", "BusName"], (((1, "A"), (2, "B")),))[1]["BusName"] == "B"


def test_records_from_powerworld_csv(tmp_path: Path) -> None:
    path = tmp_path / "bus.csv"
    path.write_text("Bus\nBusNum,BusName\n101,A\n102,B\n", encoding="utf-8")
    records = records_from_powerworld_csv(path)
    assert records == [{"BusNum": "101", "BusName": "A"}, {"BusNum": "102", "BusName": "B"}]


def test_reader_maps_powerworld_rows() -> None:
    reader = PowerWorldReader(FakeClient(), schema())  # type: ignore[arg-type]
    assert reader.read_buses()[0].number == 101
    assert reader.read_branches()[0].pair == (101, 102)
    assert reader.read_contingencies()[0].name == "CTG_A"


def test_reader_maps_violation_ctg_line_transformer_overloads() -> None:
    reader = PowerWorldReader(FakeClient(), schema())  # type: ignore[arg-type]
    violations, attempts = reader.read_thermal_violations_with_diagnostics(90.0)
    assert attempts
    assert len(violations) == 1
    assert violations[0].contingency == "CTG_A"
    assert violations[0].branch_key == "Line 101-102 1"
    assert violations[0].percent_loading == 125


def test_reader_keeps_near_overloads_when_threshold_is_90() -> None:
    fake = FakeClient()
    fake.rows["ViolationCTG"][0]["LimViolPct"] = "96.5"
    reader = PowerWorldReader(fake, schema())  # type: ignore[arg-type]
    violations, _attempts = reader.read_thermal_violations_with_diagnostics(90.0)
    assert len(violations) == 1
    assert violations[0].percent_loading == 96.5


def test_candidate_branch_aux_uses_powerworld_line_fields() -> None:
    candidate = CandidateLine(101, "A", 102, "B", 115.0, "115", 10.0)
    model = ConductorModel("115", "115 kV 1272 ACSR BITTERN", 115.0, 1, 0.0832, 0.378, "capacitive_reactance_megaohm_mile", 0.0855, 237.03, 254.2, 314.61)
    params = calculate_line_parameters(model, candidate.distance_miles, 100.0)
    aux = build_candidate_branch_aux(candidate, model, params)
    assert "DATA (Branch" in aux
    assert "LineR,LineX,LineC,LineMVA,LineMVA:1,LineMVA:2" in aux
    assert '101 102 "CS1" "Closed"' in aux
    assert "237.03 254.20 314.61" in aux
