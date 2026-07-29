from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contingency_solver.core import Branch, Bus, Contingency
from contingency_solver.storage import CONFIG_DIR

LOGGER = logging.getLogger(__name__)


class SchemaResolutionError(RuntimeError):
    pass


class SimAutoUnavailableError(RuntimeError):
    pass


class SimAutoCommandError(RuntimeError):
    def __init__(self, operation: str, raw_error: str) -> None:
        super().__init__(f"{operation} failed: {raw_error}")
        self.operation = operation
        self.raw_error = raw_error


@dataclass(frozen=True)
class SimAutoResponse:
    operation: str
    raw: Any
    error: str
    payload: tuple[Any, ...]


@dataclass(frozen=True)
class QueryAttempt:
    object_type: str
    filter_name: str
    field_count: int = 0
    row_count: int = 0
    fields: tuple[str, ...] = ()
    raw_summary: str = ""
    error: str = ""


class PowerWorldSchema:
    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw

    @classmethod
    def load(cls, path: Path | None = None) -> "PowerWorldSchema":
        schema_path = path or CONFIG_DIR / "powerworld_schema.json"
        return cls(json.loads(schema_path.read_text(encoding="utf-8")))

    def object_type(self, object_name: str) -> str:
        return str(self.raw["objects"][object_name]["object_type"])

    def object_types(self, object_name: str) -> list[str]:
        item = self.raw["objects"][object_name]
        alternatives = item.get("object_type_alternatives")
        if alternatives:
            return [str(value) for value in alternatives]
        return [self.object_type(object_name)]

    def query_filters(self, object_name: str) -> list[str]:
        return [str(value) for value in self.raw["objects"][object_name].get("query_filters", [""])]

    def alternatives(self, object_name: str, field_name: str) -> list[str]:
        return list(self.raw["objects"][object_name]["fields"][field_name])

    def resolve_field(self, object_name: str, field_name: str, available_fields: set[str]) -> str:
        lookup = {field.lower(): field for field in available_fields}
        for candidate in self.alternatives(object_name, field_name):
            if candidate.lower() in lookup:
                return lookup[candidate.lower()]
        raise SchemaResolutionError(
            f"No configured field for {object_name}.{field_name} is available. "
            f"Configured alternatives: {', '.join(self.alternatives(object_name, field_name))}."
        )

    def resolve_required(self, object_name: str, fields: list[str], available_fields: set[str]) -> dict[str, str]:
        return {field: self.resolve_field(object_name, field, available_fields) for field in fields}

    def resolve_optional(self, object_name: str, fields: list[str], available_fields: set[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for field in fields:
            try:
                resolved[field] = self.resolve_field(object_name, field, available_fields)
            except SchemaResolutionError:
                continue
        return resolved


class SimAutoClient:
    def __init__(self) -> None:
        self._simauto: Any | None = None
        self._pythoncom: Any | None = None
        self.connected = False

    def connect(self) -> None:
        if self.connected:
            return
        try:
            import pythoncom  # type: ignore[import-not-found]
            import win32com.client  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SimAutoUnavailableError(
                "PowerWorld connection requires Windows Python with pywin32 installed."
            ) from exc
        pythoncom.CoInitialize()
        self._pythoncom = pythoncom
        try:
            self._simauto = win32com.client.Dispatch("pwrworld.SimulatorAuto")
        except Exception as exc:
            raise SimAutoUnavailableError("Could not create the PowerWorld SimAuto COM object.") from exc
        self.connected = True
        LOGGER.info("Connected to PowerWorld SimAuto.")

    def close(self) -> None:
        self._simauto = None
        self.connected = False
        if self._pythoncom is not None:
            self._pythoncom.CoUninitialize()
            self._pythoncom = None

    @property
    def simauto(self) -> Any:
        if self._simauto is None:
            self.connect()
        assert self._simauto is not None
        return self._simauto

    def _checked(self, operation: str, raw: Any) -> SimAutoResponse:
        parts = tuple(raw) if isinstance(raw, (tuple, list)) else (raw,)
        error = parts[0].strip() if parts and isinstance(parts[0], str) else ""
        if error:
            LOGGER.error("SimAuto %s raw error: %s", operation, error)
            raise SimAutoCommandError(operation, error)
        return SimAutoResponse(operation, raw, error, tuple(parts[1:]))

    def call(self, operation: str, *args: Any) -> SimAutoResponse:
        return self._checked(operation, getattr(self.simauto, operation)(*args))

    def open_case(self, path: Path) -> None:
        self.call("OpenCase", str(path))

    def get_version(self) -> str:
        try:
            self.call("RunScriptCommand", 'LogMsg("Contingency Solver connection test")')
        except Exception:
            LOGGER.info("Connection test log command failed; treating COM dispatch as connected.")
        return "Connected"

    def get_field_list(self, object_type: str) -> set[str]:
        response = self.call("GetFieldList", object_type)
        fields = _flatten_strings(response.payload)
        if fields:
            return set(fields)
        raise SimAutoCommandError("GetFieldList", f"Could not inspect fields for {object_type}. Raw response: {_summarize(response.raw)}")

    def get_rows(self, object_type: str, fields: list[str], filter_name: str = "") -> list[dict[str, Any]]:
        response = self.get_rows_response(object_type, fields, filter_name)
        return records_from_response(fields, response.payload)

    def get_rows_response(self, object_type: str, fields: list[str], filter_name: str = "") -> SimAutoResponse:
        if filter_name:
            response = self.call("GetParametersMultipleElement", object_type, fields, filter_name)
        else:
            response = self.call("GetParametersMultipleElement", object_type, fields)
        LOGGER.info(
            "GetParametersMultipleElement object_type=%s filter=%r fields=%s raw=%s",
            object_type,
            filter_name,
            fields,
            _summarize(response.raw),
        )
        return response


class PowerWorldReader:
    def __init__(self, client: SimAutoClient | None = None, schema: PowerWorldSchema | None = None) -> None:
        self.client = client or SimAutoClient()
        self.schema = schema or PowerWorldSchema.load()

    def open_case(self, path: Path) -> None:
        self.client.open_case(path)

    def read_buses(self) -> list[Bus]:
        buses, _attempt = self.read_buses_with_diagnostics()
        return buses

    def read_branches(self) -> list[Branch]:
        branches, _attempt = self.read_branches_with_diagnostics()
        return branches

    def read_buses_with_diagnostics(self) -> tuple[list[Bus], QueryAttempt]:
        object_type = self.schema.object_type("bus")
        available = self.client.get_field_list(object_type)
        fields = self.schema.resolve_required("bus", ["number", "name", "nominal_kv", "latitude", "longitude", "status"], available)
        fields.update(self.schema.resolve_optional("bus", ["area", "zone", "owner", "substation"], available))
        field_values = list(fields.values())
        response = self._get_rows_response(object_type, field_values)
        rows = records_from_response(field_values, response.payload)
        attempt = QueryAttempt(
            object_type=object_type,
            filter_name="",
            field_count=len(field_values),
            row_count=len(rows),
            fields=tuple(field_values),
            raw_summary=_summarize(response.raw),
        )
        return [_bus_from_row(row, fields) for row in rows], attempt

    def read_branches_with_diagnostics(self) -> tuple[list[Branch], QueryAttempt]:
        object_type = self.schema.object_type("branch")
        available = self.client.get_field_list(object_type)
        fields = self.schema.resolve_required("branch", ["from_bus", "to_bus", "circuit", "status"], available)
        fields.update(self.schema.resolve_optional("branch", ["nominal_kv"], available))
        field_values = list(fields.values())
        response = self._get_rows_response(object_type, field_values)
        rows = records_from_response(field_values, response.payload)
        attempt = QueryAttempt(
            object_type=object_type,
            filter_name="",
            field_count=len(field_values),
            row_count=len(rows),
            fields=tuple(field_values),
            raw_summary=_summarize(response.raw),
        )
        return [_branch_from_row(row, fields) for row in rows], attempt

    def read_contingencies(self) -> list[Contingency]:
        contingencies, attempts = self.read_contingencies_with_diagnostics()
        if not contingencies:
            LOGGER.warning("No contingencies were read. Attempts: %s", attempts)
        return contingencies

    def read_contingencies_with_diagnostics(self) -> tuple[list[Contingency], list[QueryAttempt]]:
        attempts: list[QueryAttempt] = []
        for object_type in self.schema.object_types("contingency"):
            try:
                available = self.client.get_field_list(object_type)
                fields = self.schema.resolve_required("contingency", ["name"], available)
                fields.update(self.schema.resolve_optional("contingency", ["category", "skip", "solved", "action_count"], available))
            except Exception as exc:
                attempts.append(QueryAttempt(object_type=object_type, filter_name="", error=str(exc)))
                continue
            field_values = list(fields.values())
            for filter_name in self.schema.query_filters("contingency"):
                try:
                    response = self._get_rows_response(object_type, field_values, filter_name)
                    rows = records_from_response(field_values, response.payload)
                except Exception as exc:
                    attempts.append(
                        QueryAttempt(
                            object_type=object_type,
                            filter_name=filter_name,
                            field_count=len(field_values),
                            fields=tuple(field_values),
                            error=str(exc),
                        )
                    )
                    continue
                attempts.append(
                    QueryAttempt(
                        object_type=object_type,
                        filter_name=filter_name,
                        field_count=len(field_values),
                        row_count=len(rows),
                        fields=tuple(field_values),
                        raw_summary=_summarize(response.raw),
                    )
                )
                if rows:
                    contingencies = [_contingency_from_row(row, fields) for row in rows]
                    contingencies = [item for item in contingencies if item.name]
                    if contingencies:
                        LOGGER.info(
                            "Read %s contingencies using object_type=%s filter=%r fields=%s.",
                            len(contingencies),
                            object_type,
                            filter_name,
                            field_values,
                        )
                        return contingencies, attempts
        return [], attempts

    def _get_rows_response(self, object_type: str, fields: list[str], filter_name: str = "") -> SimAutoResponse:
        if hasattr(self.client, "get_rows_response"):
            return self.client.get_rows_response(object_type, fields, filter_name)
        rows = self.client.get_rows(object_type, fields, filter_name)
        values = [tuple(row.get(field) for field in fields) for row in rows]
        return SimAutoResponse("GetParametersMultipleElement", ("", tuple(fields), tuple(values)), "", (tuple(fields), tuple(values)))


def records_from_response(fields: list[str], payload: tuple[Any, ...]) -> list[dict[str, Any]]:
    if not payload:
        return []
    candidates = [item for item in payload if isinstance(item, (list, tuple))]
    if not candidates:
        return []
    data = candidates[-1]
    rows = list(data) if isinstance(data, (list, tuple)) else []
    records: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            records.append(row)
        elif isinstance(row, (list, tuple)) and len(row) == len(fields):
            records.append(dict(zip(fields, row, strict=True)))
        elif isinstance(row, (list, tuple)) and len(row) == 1 and isinstance(row[0], (list, tuple)):
            records.append(dict(zip(fields, row[0], strict=True)))
    if records:
        return records

    if len(rows) == len(fields) and all(isinstance(column, (list, tuple)) for column in rows):
        column_lengths = {len(column) for column in rows}
        if len(column_lengths) == 1:
            return [dict(zip(fields, values, strict=True)) for values in zip(*rows, strict=True)]
    return records


def _summarize(value: Any, depth: int = 0) -> str:
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, (list, tuple)):
        preview = ", ".join(_summarize(item, depth + 1) for item in list(value)[:3])
        suffix = ", ..." if len(value) > 3 else ""
        return f"{type(value).__name__}[len={len(value)}]({preview}{suffix})"
    if isinstance(value, dict):
        return f"dict[len={len(value)}]"
    text = repr(value)
    if len(text) > 80:
        text = text[:77] + "..."
    return f"{type(value).__name__}={text}"


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        output: list[str] = []
        for item in value:
            output.extend(_flatten_strings(item))
        return output
    return []


def _bus_from_row(row: dict[str, Any], fields: dict[str, str]) -> Bus:
    return Bus(
        _to_int(row[fields["number"]]),
        str(row.get(fields["name"], "")),
        _to_float(row[fields["nominal_kv"]]),
        _optional_float(row.get(fields["latitude"])),
        _optional_float(row.get(fields["longitude"])),
        _in_service(row.get(fields["status"])),
        _optional_text(row.get(fields["area"])) if "area" in fields else None,
        _optional_text(row.get(fields["zone"])) if "zone" in fields else None,
        _optional_text(row.get(fields["owner"])) if "owner" in fields else None,
        _optional_text(row.get(fields["substation"])) if "substation" in fields else None,
    )


def _branch_from_row(row: dict[str, Any], fields: dict[str, str]) -> Branch:
    return Branch(
        _to_int(row[fields["from_bus"]]),
        _to_int(row[fields["to_bus"]]),
        str(row.get(fields["circuit"], "1")).strip() or "1",
        _optional_float(row.get(fields["nominal_kv"])) if "nominal_kv" in fields else None,
        _in_service(row.get(fields["status"])),
    )


def _contingency_from_row(row: dict[str, Any], fields: dict[str, str]) -> Contingency:
    return Contingency(
        str(row.get(fields["name"], "")).strip(),
        str(row.get(fields["category"], "")).strip() if "category" in fields else "",
        _to_bool(row.get(fields["skip"])) if "skip" in fields else False,
        _optional_bool(row.get(fields["solved"])) if "solved" in fields else None,
        _optional_int(row.get(fields["action_count"])) if "action_count" in fields else None,
    )


def _to_int(value: Any) -> int:
    return int(float(str(value).strip()))


def _to_float(value: Any) -> float:
    return float(str(value).strip())


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(str(value).strip()))


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "1", "closed", "inservice", "in service"}


def _optional_bool(value: Any) -> bool | None:
    if value is None or str(value).strip() == "":
        return None
    return _to_bool(value)


def _in_service(value: Any) -> bool:
    return str(value).strip().lower() not in {"no", "false", "0", "open", "out", "outofservice", "out of service"}
