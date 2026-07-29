from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl.styles import Font

from contingency_solver.models.conductor import ConductorModel
from contingency_solver.models.run_result import CandidateResult


def _result_records(results: list[CandidateResult]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for result in results:
        record = asdict(result)
        record["classification"] = str(result.classification)
        record.pop("score_components", None)
        records.append(record)
    return records


class ExportService:
    def export_results_csv(self, results: list[CandidateResult], path: Path) -> None:
        pd.DataFrame(_result_records(results)).to_csv(path, index=False)

    def export_results_excel(
        self,
        results: list[CandidateResult],
        path: Path,
        conductor_models: dict[str, ConductorModel],
        settings: dict[str, Any],
    ) -> None:
        results_df = pd.DataFrame(_result_records(results))
        conductors_df = pd.DataFrame([asdict(model) for model in conductor_models.values()])
        settings_df = pd.DataFrame([{"setting": key, "value": str(value)} for key, value in settings.items()])
        summary = {
            "Candidate count": len(results),
            "Best score": results_df["score"].max() if not results_df.empty else None,
            "Mock mode": settings.get("mock_mode", True),
        }
        summary_df = pd.DataFrame([{"item": key, "value": value} for key, value in summary.items()])

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Run Summary", index=False)
            pd.DataFrame().to_excel(writer, sheet_name="Baseline Overloads", index=False)
            results_df.to_excel(writer, sheet_name="Candidate Results", index=False)
            pd.DataFrame().to_excel(writer, sheet_name="New Violations", index=False)
            results_df[["from_bus", "to_bus", "nominal_kv", "conductor_model", "distance_miles"]].to_excel(
                writer, sheet_name="Candidate Parameters", index=False
            )
            conductors_df.to_excel(writer, sheet_name="Conductor Models", index=False)
            settings_df.to_excel(writer, sheet_name="Run Settings", index=False)
            errors_df = results_df[results_df["error_message"].astype(str) != ""] if not results_df.empty else pd.DataFrame()
            errors_df.to_excel(writer, sheet_name="Errors", index=False)
            workbook = writer.book
            for worksheet in workbook.worksheets:
                worksheet.freeze_panes = "A2"
                worksheet.auto_filter.ref = worksheet.dimensions
                for cell in worksheet[1]:
                    cell.font = Font(bold=True)
                for column in worksheet.columns:
                    width = min(max(len(str(cell.value)) if cell.value is not None else 0 for cell in column) + 2, 38)
                    worksheet.column_dimensions[column[0].column_letter].width = width
