from dataclasses import dataclass, field
from enum import StrEnum


class CandidateClassification(StrEnum):
    SOLVED = "SOLVED"
    SOLVED_WITH_TRADEOFF = "SOLVED_WITH_TRADEOFF"
    IMPROVED = "IMPROVED"
    NO_EFFECT = "NO_EFFECT"
    WORSE = "WORSE"
    INTACT_FAILED = "INTACT_FAILED"
    CONTINGENCY_FAILED = "CONTINGENCY_FAILED"
    ERROR = "ERROR"


@dataclass
class CandidateResult:
    rank: int
    score: float
    classification: CandidateClassification
    from_bus: int
    from_bus_name: str
    to_bus: int
    to_bus_name: str
    nominal_kv: float
    conductor_model: str
    distance_miles: float
    original_loading_pct: float
    new_loading_pct: float
    loading_reduction_pct_points: float
    original_mva: float
    new_mva: float
    selected_overload_removed: bool
    new_thermal_violation_count: int
    worst_new_thermal_violation: float
    new_voltage_violation_count: int
    minimum_voltage: float
    maximum_voltage: float
    intact_solved: bool
    contingency_solved: bool
    runtime_seconds: float
    error_message: str = ""
    score_components: dict[str, float] = field(default_factory=dict)
