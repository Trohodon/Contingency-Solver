from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from contingency_solver.core import (
    CandidateClassification,
    Branch,
    CandidateLine,
    CandidateResult,
    ConductorModel,
    ScoreWeights,
    ThermalViolation,
    classify_candidate,
    score_candidate,
)
from contingency_solver.powerworld import PowerWorldReader


@dataclass(frozen=True)
class RealScreeningContext:
    working_case_path: Path
    post_contingency_case_path: Path
    selected_branch: Branch
    selected_contingency: str
    selected_issue_key: str
    original_loading_pct: float
    original_mva: float
    original_rating_mva: float
    baseline_violations: list[ThermalViolation]
    conductor_models: dict[str, ConductorModel]
    system_mva_base: float
    minimum_loading_pct: float
    meaningful_improvement_threshold_pct_points: float = 2.0
    weights: ScoreWeights = ScoreWeights()


def run_real_screening_batch(
    powerworld: PowerWorldReader,
    candidates: list[CandidateLine],
    context: RealScreeningContext,
    max_candidates: int,
) -> list[CandidateResult]:
    results: list[CandidateResult] = []
    for index, candidate in enumerate(candidates[:max_candidates], start=1):
        results.append(_run_one_candidate(powerworld, candidate, context, index))
    results.sort(key=lambda item: item.score, reverse=True)
    for rank, result in enumerate(results, start=1):
        result.rank = rank
    return results


def _run_one_candidate(
    powerworld: PowerWorldReader,
    candidate: CandidateLine,
    context: RealScreeningContext,
    index: int,
) -> CandidateResult:
    start = time.perf_counter()
    model = context.conductor_models.get(candidate.conductor_key)
    if model is None:
        return _error_result(candidate, index, context, f"No conductor model for {candidate.conductor_key} kV.", time.perf_counter() - start)

    try:
        attempts, selected_loading = powerworld.add_candidate_solve_and_read_selected_branch(
            context.post_contingency_case_path,
            candidate,
            model,
            context.system_mva_base,
            context.selected_branch,
        )
    except Exception as exc:
        return _error_result(candidate, index, context, str(exc), time.perf_counter() - start)

    error = next((attempt.error for attempt in attempts if attempt.error), "")
    intact_solved = not any(attempt.filter_name == "candidate_postctg_solve" and attempt.error for attempt in attempts)
    contingency_solved = True

    new_loading = selected_loading.percent_loading if selected_loading is not None else context.original_loading_pct
    new_mva = selected_loading.mva if selected_loading is not None else context.original_mva
    reduction = context.original_loading_pct - new_loading
    new_violations: list[ThermalViolation] = []
    worst_new = 0.0
    removed = new_loading <= 100.0

    classification = classify_candidate(
        context.original_loading_pct,
        new_loading,
        new_thermal_violation_count=len(new_violations),
        intact_solved=intact_solved,
        contingency_solved=contingency_solved,
        error_message=error,
        meaningful_improvement_threshold_pct_points=context.meaningful_improvement_threshold_pct_points,
    )
    score, components = score_candidate(
        reduction,
        removed,
        len(new_violations),
        worst_new,
        0,
        0.0,
        candidate.distance_miles,
        intact_solved,
        contingency_solved,
        context.weights,
    )
    return CandidateResult(
        index,
        round(score, 2),
        classification,
        candidate.from_bus,
        candidate.from_bus_name,
        candidate.to_bus,
        candidate.to_bus_name,
        candidate.nominal_kv,
        candidate.conductor_key,
        round(candidate.distance_miles, 2),
        context.original_loading_pct,
        round(new_loading, 2),
        round(reduction, 2),
        context.original_mva,
        round(new_mva, 2),
        removed,
        len(new_violations),
        round(worst_new, 2),
        0,
        0.0,
        0.0,
        intact_solved,
        contingency_solved,
        round(time.perf_counter() - start, 2),
        error,
        components,
    )


def _find_selected_violation(violations: list[ThermalViolation], selected_issue_key: str) -> ThermalViolation | None:
    normalized = _normalize_issue(selected_issue_key)
    exact = [item for item in violations if _normalize_issue(item.branch_key) == normalized]
    if exact:
        return max(exact, key=lambda item: item.percent_loading)
    contains = [item for item in violations if normalized and normalized in _normalize_issue(item.branch_key)]
    if contains:
        return max(contains, key=lambda item: item.percent_loading)
    return None


def _new_thermal_violations(baseline: list[ThermalViolation], candidate: list[ThermalViolation]) -> list[ThermalViolation]:
    baseline_keys = {(_normalize_issue(item.branch_key), item.contingency) for item in baseline}
    return [item for item in candidate if (_normalize_issue(item.branch_key), item.contingency) not in baseline_keys]


def _normalize_issue(value: str) -> str:
    return " ".join(value.lower().replace("!", "").split())


def _error_result(candidate: CandidateLine, index: int, context: RealScreeningContext, error: str, runtime: float) -> CandidateResult:
    return CandidateResult(
        index,
        -100.0,
        CandidateClassification.ERROR,
        candidate.from_bus,
        candidate.from_bus_name,
        candidate.to_bus,
        candidate.to_bus_name,
        candidate.nominal_kv,
        candidate.conductor_key,
        round(candidate.distance_miles, 2),
        context.original_loading_pct,
        context.original_loading_pct,
        0.0,
        context.original_mva,
        context.original_mva,
        False,
        0,
        0.0,
        0,
        0.0,
        0.0,
        False,
        False,
        round(runtime, 2),
        error,
        {"solution_failure_penalty": -100.0},
    )
