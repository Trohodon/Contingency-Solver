from __future__ import annotations

import json
import logging
import tempfile
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contingency_solver.core import Branch, Bus, Contingency, ThermalViolation
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
        try:
            raw = getattr(self.simauto, operation)(*args)
        except Exception as exc:
            LOGGER.exception("SimAuto %s raised an exception.", operation)
            raise SimAutoCommandError(operation, str(exc)) from exc
        return self._checked(operation, raw)

    def open_case(self, path: Path) -> None:
        self.call("OpenCase", str(path))

    def get_version(self) -> str:
        try:
            self.call("RunScriptCommand", 'LogMsg("Contingency Solver connection test")')
        except Exception:
            LOGGER.info("Connection test log command failed; treating COM dispatch as connected.")
        return "Connected"

    def run_script_command(self, command: str) -> None:
        self.call("RunScriptCommand", command)

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
        response = self.call("GetParametersMultipleElement", object_type, fields, filter_name)
        LOGGER.info(
            "GetParametersMultipleElement object_type=%s filter=%r fields=%s raw=%s",
            object_type,
            filter_name,
            fields,
            _summarize(response.raw),
        )
        return response

    def export_rows_csv(self, object_type: str, fields: list[str]) -> list[dict[str, Any]]:
        with tempfile.NamedTemporaryFile(prefix=f"contingency_solver_{object_type}_", suffix=".csv", delete=False) as handle:
            csv_path = Path(handle.name)
        clean_path = str(csv_path).replace("\\", "/")
        field_text = ", ".join(fields)
        command = f'SaveData("{clean_path}", CSV, {object_type}, [ALL], [{field_text}], "");'
        LOGGER.info("Exporting PowerWorld object via SaveData: %s", command)
        try:
            self.run_script_command(command)
            return records_from_powerworld_csv(csv_path)
        finally:
            try:
                csv_path.unlink(missing_ok=True)
            except Exception:
                LOGGER.warning("Could not remove temporary PowerWorld export %s.", csv_path)


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
        raw_summary = _summarize(response.raw)
        if not rows and hasattr(self.client, "export_rows_csv"):
            try:
                rows = self.client.export_rows_csv(object_type, field_values)
                raw_summary += f"; csv_fallback_rows={len(rows)}"
            except Exception as exc:
                raw_summary += f"; csv_fallback_error={exc}"
        attempt = QueryAttempt(
            object_type=object_type,
            filter_name="",
            field_count=len(field_values),
            row_count=len(rows),
            fields=tuple(field_values),
            raw_summary=raw_summary,
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
        raw_summary = _summarize(response.raw)
        if not rows and hasattr(self.client, "export_rows_csv"):
            try:
                rows = self.client.export_rows_csv(object_type, field_values)
                raw_summary += f"; csv_fallback_rows={len(rows)}"
            except Exception as exc:
                raw_summary += f"; csv_fallback_error={exc}"
        attempt = QueryAttempt(
            object_type=object_type,
            filter_name="",
            field_count=len(field_values),
            row_count=len(rows),
            fields=tuple(field_values),
            raw_summary=raw_summary,
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
                    raw_summary = _summarize(response.raw)
                    if not rows and hasattr(self.client, "export_rows_csv"):
                        try:
                            if object_type.lower() == "contingency":
                                self.client.run_script_command("EnterMode(Contingency);")
                            rows = self.client.export_rows_csv(object_type, field_values)
                            raw_summary += f"; csv_fallback_rows={len(rows)}"
                        except Exception as exc:
                            raw_summary += f"; csv_fallback_error={exc}"
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
                        raw_summary=raw_summary,
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

    def read_thermal_violations_with_diagnostics(self) -> tuple[list[ThermalViolation], list[QueryAttempt]]:
        attempts: list[QueryAttempt] = []
        try:
            self.client.run_script_command("EnterMode(Contingency);")
        except Exception as exc:
            attempts.append(QueryAttempt(object_type="ViolationCTG", filter_name="", error=f"EnterMode(Contingency) failed: {exc}"))

        for object_type in self.schema.object_types("violation_ctg"):
            try:
                available = self.client.get_field_list(object_type)
                fields = self.schema.resolve_required("violation_ctg", ["contingency", "violation_id", "value", "percent"], available)
                fields.update(self.schema.resolve_optional("violation_ctg", ["limit"], available))
                category = self._resolve_violation_category_field(available)
                if category is not None:
                    fields["category"] = category
            except Exception as exc:
                attempts.append(QueryAttempt(object_type=object_type, filter_name="", error=str(exc)))
                # SaveData can still work when GetFieldList is touchy, so try canonical configured names.
                fields = self._default_violation_ctg_fields()

            field_values = list(fields.values())
            for filter_name in self.schema.query_filters("violation_ctg"):
                try:
                    response = self._get_rows_response(object_type, field_values, filter_name)
                    rows = records_from_response(field_values, response.payload)
                    raw_summary = _summarize(response.raw)
                    if not rows and hasattr(self.client, "export_rows_csv"):
                        try:
                            rows = self.client.export_rows_csv(object_type, field_values)
                            raw_summary += f"; csv_fallback_rows={len(rows)}"
                        except Exception as exc:
                            raw_summary += f"; csv_fallback_error={exc}"
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

                violations = [_thermal_violation_from_row(row, fields) for row in rows]
                violations = [item for item in violations if _is_line_or_transformer_overload(item)]
                violations.sort(key=lambda item: item.percent_loading, reverse=True)
                attempts.append(
                    QueryAttempt(
                        object_type=object_type,
                        filter_name=filter_name,
                        field_count=len(field_values),
                        row_count=len(violations),
                        fields=tuple(field_values),
                        raw_summary=raw_summary,
                    )
                )
                if violations:
                    LOGGER.info("Read %s line/transformer overload rows from ViolationCTG.", len(violations))
                    return violations, attempts
        return [], attempts

    def _default_violation_ctg_fields(self) -> dict[str, str]:
        return {
            "contingency": self.schema.alternatives("violation_ctg", "contingency")[0],
            "violation_id": self.schema.alternatives("violation_ctg", "violation_id")[0],
            "limit": self.schema.alternatives("violation_ctg", "limit")[0],
            "value": self.schema.alternatives("violation_ctg", "value")[0],
            "percent": self.schema.alternatives("violation_ctg", "percent")[0],
            "category": self.schema.alternatives("violation_ctg", "category")[0],
        }

    def _resolve_violation_category_field(self, available: set[str]) -> str | None:
        lookup = {field.lower(): field for field in available}
        for candidate in ("LimViolCat", "Category"):
            if candidate.lower() in lookup:
                return lookup[candidate.lower()]
        return None

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


def records_from_powerworld_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    rows = [[cell.strip() for cell in row] for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        return []
    header_index = 0
    if len(rows) >= 2 and len(rows[0]) <= 1:
        header_index = 1
    headers = [header for header in rows[header_index] if header]
    records: list[dict[str, Any]] = []
    for row in rows[header_index + 1 :]:
        padded = row + [""] * max(0, len(headers) - len(row))
        records.append(dict(zip(headers, padded[: len(headers)], strict=True)))
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


def _thermal_violation_from_row(row: dict[str, Any], fields: dict[str, str]) -> ThermalViolation:
    violation_id = str(row.get(fields["violation_id"], "")).strip()
    return ThermalViolation(
        branch_key=violation_id,
        from_bus=0,
        to_bus=0,
        circuit_id="",
        mva=_optional_float(row.get(fields["value"])) or 0.0,
        rating_mva=(_optional_float(row.get(fields["limit"])) if "limit" in fields else 0.0) or 0.0,
        percent_loading=_optional_float(row.get(fields["percent"])) or 0.0,
        contingency=str(row.get(fields["contingency"], "")).strip(),
        category=str(row.get(fields["category"], "")).strip() if "category" in fields else "",
    )


def _is_line_or_transformer_overload(item: ThermalViolation) -> bool:
    if item.percent_loading <= 100.0:
        return False
    text = f"{item.branch_key} {item.category}".lower()
    excluded_terms = ("volt", "voltage", "interface", "bus pair angle", "dv/dq", "mvar")
    return not any(term in text for term in excluded_terms)


def _to_int(value: Any) -> int:
    return int(float(str(value).strip()))


def _to_float(value: Any) -> float:
    return float(str(value).strip())


def _optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        text = str(value).strip().replace(",", "").replace("%", "")
        return float(text)
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
