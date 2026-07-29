from contingency_solver.models.run_result import CandidateClassification


def classify_candidate(
    original_loading_pct: float,
    new_loading_pct: float,
    applicable_limit_pct: float = 100.0,
    new_thermal_violation_count: int = 0,
    new_voltage_violation_count: int = 0,
    intact_solved: bool = True,
    contingency_solved: bool = True,
    error_message: str = "",
    meaningful_improvement_threshold_pct_points: float = 2.0,
) -> CandidateClassification:
    if error_message:
        return CandidateClassification.ERROR
    if not intact_solved:
        return CandidateClassification.INTACT_FAILED
    if not contingency_solved:
        return CandidateClassification.CONTINGENCY_FAILED

    reduction = original_loading_pct - new_loading_pct
    removed = new_loading_pct <= applicable_limit_pct
    has_tradeoff = new_thermal_violation_count > 0 or new_voltage_violation_count > 0
    if removed and not has_tradeoff:
        return CandidateClassification.SOLVED
    if removed and has_tradeoff:
        return CandidateClassification.SOLVED_WITH_TRADEOFF
    if reduction > meaningful_improvement_threshold_pct_points:
        return CandidateClassification.IMPROVED
    if abs(reduction) <= meaningful_improvement_threshold_pct_points:
        return CandidateClassification.NO_EFFECT
    return CandidateClassification.WORSE
