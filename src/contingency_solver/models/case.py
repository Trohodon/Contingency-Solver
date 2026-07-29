from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CaseSummary:
    path: Path
    bus_count: int
    branch_count: int
    supported_voltage_bus_count: int
    buses_with_coordinates: int
    powerworld_version: str | None = None

    @property
    def display_name(self) -> str:
        return self.path.name
