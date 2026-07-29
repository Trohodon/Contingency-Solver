from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreWeights:
    loading_reduction: float = 2.0
    overload_removed_bonus: float = 35.0
    new_thermal_violation_penalty: float = 15.0
    new_voltage_violation_penalty: float = 12.0
    line_length_penalty: float = 0.2
    solution_failure_penalty: float = 100.0


def score_candidate(
    loading_reduction_pct_points: float,
    selected_overload_removed: bool,
    new_thermal_violation_count: int,
    worst_new_thermal_violation_pct: float,
    new_voltage_violation_count: int,
    voltage_severity: float,
    distance_miles: float,
    intact_solved: bool,
    contingency_solved: bool,
    weights: ScoreWeights,
) -> tuple[float, dict[str, float]]:
    components = {
        "loading_reduction": loading_reduction_pct_points * weights.loading_reduction,
        "overload_removed_bonus": weights.overload_removed_bonus if selected_overload_removed else 0.0,
        "new_thermal_violation_penalty": -new_thermal_violation_count * weights.new_thermal_violation_penalty,
        "thermal_severity_penalty": -max(0.0, worst_new_thermal_violation_pct - 100.0),
        "new_voltage_violation_penalty": -new_voltage_violation_count * weights.new_voltage_violation_penalty,
        "voltage_severity_penalty": -voltage_severity,
        "line_length_penalty": -distance_miles * weights.line_length_penalty,
        "solution_failure_penalty": 0.0 if intact_solved and contingency_solved else -weights.solution_failure_penalty,
    }
    return sum(components.values()), components
