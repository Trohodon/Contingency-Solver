from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)


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

    @property
    def succeeded(self) -> bool:
        return self.error == ""


class SimAutoClient:
    """Thin checked wrapper around the PowerWorld SimAuto COM object."""

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
            LOGGER.exception("pywin32 is not available; SimAuto cannot be used.")
            raise SimAutoUnavailableError(
                "pywin32 is not installed or this is not a Windows Python environment. "
                "Install dependencies on Windows before connecting to PowerWorld."
            ) from exc

        pythoncom.CoInitialize()
        self._pythoncom = pythoncom
        try:
            self._simauto = win32com.client.Dispatch("pwrworld.SimulatorAuto")
        except Exception as exc:
            LOGGER.exception("PowerWorld SimAuto COM dispatch failed.")
            raise SimAutoUnavailableError(
                "Could not create PowerWorld SimAuto COM object. Confirm PowerWorld Simulator and SimAuto are installed/licensed."
            ) from exc
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
        if isinstance(raw, tuple):
            parts = raw
        elif isinstance(raw, list):
            parts = tuple(raw)
        else:
            parts = (raw,)
        error = ""
        if parts and isinstance(parts[0], str):
            error = parts[0].strip()
        response = SimAutoResponse(operation=operation, raw=raw, error=error, payload=tuple(parts[1:]))
        if error:
            LOGGER.error("SimAuto %s raw error: %s", operation, error)
            raise SimAutoCommandError(operation, error)
        LOGGER.debug("SimAuto %s succeeded.", operation)
        return response

    def call(self, operation: str, *args: Any) -> SimAutoResponse:
        method = getattr(self.simauto, operation)
        LOGGER.info("Calling SimAuto %s.", operation)
        return self._checked(operation, method(*args))

    def open_case(self, path: Path) -> None:
        self.call("OpenCase", str(path))

    def get_version(self) -> str | None:
        for operation in ("GetParametersSingleElement", "GetSpecificFieldList"):
            if not hasattr(self.simauto, operation):
                continue
        try:
            response = self.call("RunScriptCommand", "LogMsg(\"Contingency Solver connection test\")")
            return "Connected"
        except Exception:
            LOGGER.info("Version query is not confirmed for this PowerWorld installation.")
            return "Connected"

    def run_script_command(self, command: str) -> None:
        self.call("RunScriptCommand", command)

    def get_field_list(self, object_type: str) -> set[str]:
        candidates = [
            ("GetFieldList", (object_type,)),
            ("GetFieldList", (object_type, "")),
        ]
        last_error: Exception | None = None
        for operation, args in candidates:
            try:
                response = self.call(operation, *args)
            except Exception as exc:
                last_error = exc
                continue
            fields = _flatten_strings(response.payload)
            if fields:
                return set(fields)
        raise SimAutoCommandError(
            "GetFieldList",
            f"Could not inspect available fields for object type '{object_type}'. Last error: {last_error}",
        )

    def get_parameters_multiple_element(self, object_type: str, fields: list[str], filter_name: str = "") -> list[dict[str, Any]]:
        response = self.call("GetParametersMultipleElement", object_type, fields, filter_name)
        return records_from_response(fields, response.payload)


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_strings(item))
        return result
    return []


def records_from_response(fields: list[str], payload: tuple[Any, ...]) -> list[dict[str, Any]]:
    if not payload:
        return []
    data = payload[-1]
    rows: list[Any]
    if isinstance(data, tuple):
        rows = list(data)
    elif isinstance(data, list):
        rows = data
    else:
        return []

    records: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            records.append(row)
            continue
        if not isinstance(row, (list, tuple)):
            continue
        if len(row) == len(fields):
            records.append(dict(zip(fields, row, strict=True)))
            continue
        if len(row) == 1 and isinstance(row[0], (list, tuple)) and len(row[0]) == len(fields):
            records.append(dict(zip(fields, row[0], strict=True)))
    return records
