from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from contingency_solver.constants import DEFAULT_CONDUCTOR_MODELS_PATH, DEFAULT_SETTINGS_PATH
from contingency_solver.models.conductor import ConductorModel
from contingency_solver.utilities.paths import user_data_dir


class SettingsService:
    def __init__(self) -> None:
        self.settings_path = user_data_dir() / "settings.json"
        self.conductor_path = user_data_dir() / "conductor_models.json"
        if not self.settings_path.exists():
            shutil.copyfile(DEFAULT_SETTINGS_PATH, self.settings_path)
        if not self.conductor_path.exists():
            shutil.copyfile(DEFAULT_CONDUCTOR_MODELS_PATH, self.conductor_path)

    def load_settings(self) -> dict[str, Any]:
        return json.loads(self.settings_path.read_text(encoding="utf-8"))

    def save_settings(self, settings: dict[str, Any]) -> None:
        self.settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def load_conductor_models(self) -> tuple[float, float, dict[str, ConductorModel]]:
        raw = json.loads(self.conductor_path.read_text(encoding="utf-8"))
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

    def save_conductor_models(
        self,
        system_mva_base: float,
        voltage_tolerance_kv: float,
        models: dict[str, ConductorModel],
    ) -> None:
        raw = {
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
        self.conductor_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def restore_default_conductors(self) -> None:
        shutil.copyfile(DEFAULT_CONDUCTOR_MODELS_PATH, self.conductor_path)

    def import_conductors(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "line_models" not in data:
            raise ValueError("Conductor file must contain line_models.")
        self.conductor_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def export_conductors(self, path: Path) -> None:
        shutil.copyfile(self.conductor_path, path)
