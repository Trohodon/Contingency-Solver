from __future__ import annotations

import csv
import json
import logging
import shutil
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font

from contingency_solver import __version__
from contingency_solver.core import CandidateResult, ConductorModel, result_to_row

LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
USER_DATA = ROOT / "user_data"
LOG_DIR = USER_DATA / "logs"
EXPORT_DIR = USER_DATA / "exports"
WORKING_CASE_DIR = USER_DATA / "working_cases"


def ensure_dirs() -> None:
    for path in (USER_DATA, LOG_DIR, EXPORT_DIR, WORKING_CASE_DIR):
        path.mkdir(exist_ok=True)


def create_working_case_copy(source_path: Path) -> Path:
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_stem = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in source_path.stem)
    destination = WORKING_CASE_DIR / f"{safe_stem}_{timestamp}{source_path.suffix}"
    shutil.copy2(source_path, destination)
    LOGGER.info("Created PowerWorld working case copy. source=%s destination=%s", source_path, destination)
    return destination


def create_post_contingency_case_path(source_path: Path, contingency_name: str) -> Path:
    ensure_dirs()
    safe_stem = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in source_path.stem)
    safe_ctg = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in contingency_name)[:80]
    return WORKING_CASE_DIR / f"{safe_stem}_{safe_ctg}_postctg_base{source_path.suffix}"


def load_settings() -> dict[str, Any]:
    ensure_dirs()
    path = USER_DATA / "settings.json"
    if not path.exists():
        shutil.copyfile(CONFIG_DIR / "default_settings.json", path)
    return json.loads(path.read_text(encoding="utf-8"))


def save_settings(settings: dict[str, Any]) -> None:
    ensure_dirs()
    (USER_DATA / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def load_conductors() -> tuple[float, float, dict[str, ConductorModel]]:
    ensure_dirs()
    path = USER_DATA / "conductor_models.json"
    if not path.exists():
        shutil.copyfile(CONFIG_DIR / "conductor_models.json", path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    models = {
        key: ConductorModel(
            key=key,
            name=value["name"],
            nominal_kv=float(value["nominal_kv"]),
            bundle_count=value.get("bundle_count"),
            resistance_ohm_per_mile=value.get("resistance_ohm_per_mile"),
            reactance_ohm_per_mile=value.get("reactance_ohm_per_mile"),
            charging_input_type=value.get("charging_input_type", "susceptance_per_mile"),
            charging_value_per_mile=value.get("charging_value_per_mile"),
            rate_a_mva=value.get("rate_a_mva"),
            rate_b_mva=value.get("rate_b_mva"),
            rate_c_mva=value.get("rate_c_mva"),
            circuit_count=int(value.get("circuit_count", 1)),
            notes=value.get("notes", ""),
        )
        for key, value in raw["line_models"].items()
    }
    return float(raw["system_mva_base"]), float(raw["voltage_tolerance_kv"]), models


def save_conductors(system_mva_base: float, voltage_tolerance_kv: float, models: dict[str, ConductorModel]) -> None:
    ensure_dirs()
    data = {
        "system_mva_base": system_mva_base,
        "voltage_tolerance_kv": voltage_tolerance_kv,
        "line_models": {
            key: {
                "name": model.name,
                "nominal_kv": model.nominal_kv,
                "bundle_count": model.bundle_count,
                "resistance_ohm_per_mile": model.resistance_ohm_per_mile,
                "reactance_ohm_per_mile": model.reactance_ohm_per_mile,
                "charging_input_type": model.charging_input_type,
                "charging_value_per_mile": model.charging_value_per_mile,
                "rate_a_mva": model.rate_a_mva,
                "rate_b_mva": model.rate_b_mva,
                "rate_c_mva": model.rate_c_mva,
                "circuit_count": model.circuit_count,
                "notes": model.notes,
            }
            for key, model in models.items()
        },
    }
    (USER_DATA / "conductor_models.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def restore_default_conductors() -> None:
    ensure_dirs()
    shutil.copyfile(CONFIG_DIR / "conductor_models.json", USER_DATA / "conductor_models.json")


def export_csv(results: list[CandidateResult], path: Path) -> None:
    rows = [result_to_row(result) for result in results]
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def export_excel(
    results: list[CandidateResult],
    path: Path,
    conductor_models: dict[str, ConductorModel],
    settings: dict[str, Any],
) -> None:
    results_df = pd.DataFrame([result_to_row(result) for result in results])
    conductors_df = pd.DataFrame([asdict(model) for model in conductor_models.values()])
    settings_df = pd.DataFrame([{"setting": key, "value": str(value)} for key, value in settings.items()])
    summary_df = pd.DataFrame(
        [
            {"item": "Candidate count", "value": len(results)},
            {"item": "Best score", "value": results_df["Score"].max() if not results_df.empty else None},
            {"item": "Mock mode", "value": settings.get("mock_mode", True)},
        ]
    )

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Run Summary", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="Baseline Overloads", index=False)
        results_df.to_excel(writer, sheet_name="Candidate Results", index=False)
        pd.DataFrame().to_excel(writer, sheet_name="New Violations", index=False)
        params = results_df[["From Bus", "To Bus", "Nominal kV", "Conductor", "Distance"]] if not results_df.empty else pd.DataFrame()
        params.to_excel(writer, sheet_name="Candidate Parameters", index=False)
        conductors_df.to_excel(writer, sheet_name="Conductor Models", index=False)
        settings_df.to_excel(writer, sheet_name="Run Settings", index=False)
        errors_df = results_df[results_df["Error"].astype(str) != ""] if not results_df.empty else pd.DataFrame()
        errors_df.to_excel(writer, sheet_name="Errors", index=False)
        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for cell in worksheet[1]:
                cell.font = Font(bold=True)
            for column in worksheet.columns:
                width = min(max(len(str(cell.value)) if cell.value is not None else 0 for cell in column) + 2, 38)
                worksheet.column_dimensions[column[0].column_letter].width = width


def save_run_history(selected_contingency: str, selected_branch: str, settings: dict[str, Any], results: list[CandidateResult]) -> int:
    ensure_dirs()
    path = USER_DATA / "run_history.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_alias TEXT,
                run_timestamp TEXT NOT NULL,
                selected_contingency TEXT,
                selected_branch TEXT,
                settings_snapshot TEXT,
                candidate_results TEXT,
                status TEXT,
                application_version TEXT
            )
            """
        )
        cursor = connection.execute(
            """
            INSERT INTO runs (
                case_alias, run_timestamp, selected_contingency, selected_branch,
                settings_snapshot, candidate_results, status, application_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Mock sample case",
                datetime.now().isoformat(timespec="seconds"),
                selected_contingency,
                selected_branch,
                json.dumps(settings),
                json.dumps([result_to_row(result) for result in results]),
                "MOCK_COMPLETE",
                __version__,
            ),
        )
        return int(cursor.lastrowid)
