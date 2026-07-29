from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from contingency_solver.analysis.candidate_generator import voltage_class
from contingency_solver.constants import CONFIG_DIR
from contingency_solver.models.branch import Branch
from contingency_solver.models.bus import Bus
from contingency_solver.models.case import CaseSummary
from contingency_solver.powerworld.schema import PowerWorldSchema
from contingency_solver.powerworld.simauto_client import SimAutoClient

LOGGER = logging.getLogger(__name__)


class CaseManager:
    def __init__(self, client: SimAutoClient, schema: PowerWorldSchema | None = None) -> None:
        self.client = client
        self.schema = schema or PowerWorldSchema.load(CONFIG_DIR / "powerworld_schema.json")
        self.loaded_case: Path | None = None

    def open_case(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        self.client.open_case(path)
        self.loaded_case = path
        LOGGER.info("Loaded PowerWorld case %s.", path)

    def read_buses(self, voltage_tolerance_kv: float) -> list[Bus]:
        object_type = self.schema.object_type("bus")
        available = self.client.get_field_list(object_type)
        field_map = self.schema.resolve_fields(
            "bus",
            ["number", "name", "nominal_kv", "latitude", "longitude", "status"],
            available,
        )
        field_map.update(self.schema.resolve_optional_fields("bus", ["area", "zone", "owner", "substation"], available))
        rows = self.client.get_parameters_multiple_element(object_type, list(field_map.values()))
        buses = [_bus_from_row(row, field_map) for row in rows]
        LOGGER.info("Read %s buses from PowerWorld.", len(buses))
        return buses

    def read_branches(self) -> list[Branch]:
        object_type = self.schema.object_type("branch")
        available = self.client.get_field_list(object_type)
        field_map = self.schema.resolve_fields("branch", ["from_bus", "to_bus", "circuit", "status"], available)
        field_map.update(self.schema.resolve_optional_fields("branch", ["nominal_kv"], available))
        rows = self.client.get_parameters_multiple_element(object_type, list(field_map.values()))
        branches = [_branch_from_row(row, field_map) for row in rows]
        LOGGER.info("Read %s branches from PowerWorld.", len(branches))
        return branches

    def read_case_summary(self, path: Path, voltage_tolerance_kv: float) -> CaseSummary:
        buses = self.read_buses(voltage_tolerance_kv)
        branches = self.read_branches()
        supported = sum(1 for bus in buses if voltage_class(bus.nominal_kv, voltage_tolerance_kv) is not None)
        with_coordinates = sum(1 for bus in buses if bus.has_valid_coordinates)
        return CaseSummary(
            path=path,
            bus_count=len(buses),
            branch_count=len(branches),
            supported_voltage_bus_count=supported,
            buses_with_coordinates=with_coordinates,
            powerworld_version=self.client.get_version(),
        )


def _bus_from_row(row: dict[str, Any], field_map: dict[str, str]) -> Bus:
    return Bus(
        number=_to_int(row[field_map["number"]]),
        name=str(row.get(field_map["name"], "")),
        nominal_kv=_to_float(row[field_map["nominal_kv"]]),
        latitude=_optional_float(row.get(field_map["latitude"])),
        longitude=_optional_float(row.get(field_map["longitude"])),
        in_service=_is_in_service(row.get(field_map["status"])),
        area=_optional_row_value(row, field_map, "area"),
        zone=_optional_row_value(row, field_map, "zone"),
        owner=_optional_row_value(row, field_map, "owner"),
        substation=_optional_row_value(row, field_map, "substation"),
    )


def _branch_from_row(row: dict[str, Any], field_map: dict[str, str]) -> Branch:
    return Branch(
        from_bus=_to_int(row[field_map["from_bus"]]),
        to_bus=_to_int(row[field_map["to_bus"]]),
        circuit_id=str(row.get(field_map["circuit"], "1")).strip() or "1",
        nominal_kv=_optional_float(row.get(field_map["nominal_kv"])) if "nominal_kv" in field_map else None,
        in_service=_is_in_service(row.get(field_map["status"])),
    )


def _to_int(value: Any) -> int:
    return int(float(str(value).strip()))


def _to_float(value: Any) -> float:
    return float(str(value).strip())


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_row_value(row: dict[str, Any], field_map: dict[str, str], canonical_name: str) -> str | None:
    if canonical_name not in field_map:
        return None
    return _optional_str(row.get(field_map[canonical_name]))


def _is_in_service(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip().lower()
    return text not in {"no", "false", "0", "open", "out", "outofservice", "out of service"}
