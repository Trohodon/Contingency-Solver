from __future__ import annotations

import logging
from typing import Any

from contingency_solver.constants import CONFIG_DIR
from contingency_solver.models.contingency import Contingency
from contingency_solver.powerworld.schema import PowerWorldSchema
from contingency_solver.powerworld.simauto_client import SimAutoClient

LOGGER = logging.getLogger(__name__)


class ContingencyService:
    def __init__(self, client: SimAutoClient, schema: PowerWorldSchema | None = None) -> None:
        self.client = client
        self.schema = schema or PowerWorldSchema.load(CONFIG_DIR / "powerworld_schema.json")

    def read_contingencies(self) -> list[Contingency]:
        object_type = self.schema.object_type("contingency")
        available = self.client.get_field_list(object_type)
        field_map = self.schema.resolve_fields("contingency", ["name"], available)
        field_map.update(self.schema.resolve_optional_fields("contingency", ["category", "skip", "solved", "action_count"], available))
        rows = self.client.get_parameters_multiple_element(object_type, list(field_map.values()))
        contingencies = [_contingency_from_row(row, field_map) for row in rows]
        LOGGER.info("Read %s contingencies from PowerWorld.", len(contingencies))
        return contingencies


def _contingency_from_row(row: dict[str, Any], field_map: dict[str, str]) -> Contingency:
    return Contingency(
        name=str(row.get(field_map["name"], "")).strip(),
        category=str(row.get(field_map["category"], "")).strip() if "category" in field_map else "",
        skipped=_to_bool(row.get(field_map["skip"])) if "skip" in field_map else False,
        solved=_optional_bool(row.get(field_map["solved"])) if "solved" in field_map else None,
        action_count=_optional_int(row.get(field_map["action_count"])) if "action_count" in field_map else None,
        actions=[],
    )


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value).strip()))


def _optional_bool(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    return _to_bool(value)


def _to_bool(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"yes", "true", "1", "closed", "inservice", "in service"}
