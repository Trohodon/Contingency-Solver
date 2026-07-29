from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from contingency_solver import __version__
from contingency_solver.models.run_result import CandidateResult
from contingency_solver.utilities.paths import user_data_dir


class HistoryService:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (user_data_dir() / "run_history.sqlite")
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as connection:
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

    def save_mock_run(
        self,
        selected_contingency: str,
        selected_branch: str,
        settings: dict,
        results: list[CandidateResult],
        status: str = "MOCK_COMPLETE",
    ) -> int:
        payload = json.dumps([asdict(result) | {"classification": str(result.classification)} for result in results])
        with sqlite3.connect(self.path) as connection:
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
                    payload,
                    status,
                    __version__,
                ),
            )
            return int(cursor.lastrowid)
