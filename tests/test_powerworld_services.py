from typing import Any

from contingency_solver.powerworld.case_manager import CaseManager
from contingency_solver.powerworld.contingency_service import ContingencyService
from contingency_solver.powerworld.schema import PowerWorldSchema


class FakeClient:
    def __init__(self) -> None:
        self.available = {
            "Bus": {"BusNum", "BusName", "BusNomVolt", "Latitude", "Longitude", "Status", "AreaNum", "ZoneNum", "OwnerNum", "SubName"},
            "Branch": {"BusNum", "BusNum:1", "LineCircuit", "Status", "NomkV"},
            "Contingency": {"CTGLabel", "Category", "Skip", "Solved", "NumActions"},
        }
        self.rows = {
            "Bus": [
                {
                    "BusNum": "101",
                    "BusName": "A",
                    "BusNomVolt": "115",
                    "Latitude": "40.0",
                    "Longitude": "-82.0",
                    "Status": "Closed",
                    "AreaNum": "1",
                    "ZoneNum": "2",
                    "OwnerNum": "3",
                    "SubName": "Sub",
                }
            ],
            "Branch": [{"BusNum": "101", "BusNum:1": "102", "LineCircuit": "1", "Status": "Closed", "NomkV": "115"}],
            "Contingency": [{"CTGLabel": "CTG_A", "Category": "Thermal", "Skip": "No", "Solved": "Yes", "NumActions": "1"}],
        }

    def get_field_list(self, object_type: str) -> set[str]:
        return self.available[object_type]

    def get_parameters_multiple_element(self, object_type: str, fields: list[str], filter_name: str = "") -> list[dict[str, Any]]:
        return [{field: row[field] for field in fields} for row in self.rows[object_type]]


def _schema() -> PowerWorldSchema:
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


def test_case_manager_reads_bus_and_branch_models() -> None:
    manager = CaseManager(FakeClient(), _schema())  # type: ignore[arg-type]
    buses = manager.read_buses(1.0)
    branches = manager.read_branches()
    assert buses[0].number == 101
    assert buses[0].has_valid_coordinates
    assert branches[0].normalized_pair == (101, 102)


def test_contingency_service_reads_contingencies() -> None:
    service = ContingencyService(FakeClient(), _schema())  # type: ignore[arg-type]
    contingencies = service.read_contingencies()
    assert contingencies[0].name == "CTG_A"
    assert contingencies[0].solved is True
    assert contingencies[0].action_count == 1
