from pathlib import Path

from contingency_solver.core import Branch, CandidateClassification, CandidateLine, ConductorModel, ThermalViolation
from contingency_solver.powerworld import QueryAttempt
from contingency_solver.services.real_screening import RealScreeningContext, run_real_screening_batch


class FakePowerWorld:
    def __init__(self, violations: list[ThermalViolation]) -> None:
        self.violations = violations
        self.calls = 0

    def add_candidate_solve_and_read_current_violations(
        self,
        post_contingency_case_path: Path,
        candidate: CandidateLine,
        conductor_model: ConductorModel,
        system_mva_base: float,
        minimum_loading_pct: float,
    ):
        self.calls += 1
        return [QueryAttempt("PowerFlow", "candidate_postctg_solve", row_count=1)], self.violations


def _context(model: ConductorModel) -> RealScreeningContext:
    baseline = [ThermalViolation("Line A-B", 1, 2, "1", 120.0, 100.0, 120.0, "CTG_A")]
    return RealScreeningContext(
        working_case_path=Path("working.pwb"),
        post_contingency_case_path=Path("postctg.pwb"),
        selected_branch=Branch(1, 2, "1", 115.0),
        selected_contingency="CTG_A",
        selected_issue_key="Line A-B",
        original_loading_pct=120.0,
        original_mva=120.0,
        original_rating_mva=100.0,
        baseline_violations=baseline,
        conductor_models={"115": model},
        system_mva_base=100.0,
        minimum_loading_pct=90.0,
    )


def test_real_screening_batch_uses_live_selected_branch_loading() -> None:
    candidate = CandidateLine(1, "A", 2, "B", 115.0, "115", 10.0)
    model = ConductorModel("115", "test", 115.0, 1, 0.0832, 0.378, "capacitive_reactance_megaohm_mile", 0.0855, 237.03, 254.2, 314.61)
    fake = FakePowerWorld([ThermalViolation("Line A-B", 1, 2, "1", 105.0, 100.0, 105.0)])

    results = run_real_screening_batch(fake, [candidate], _context(model), 1)  # type: ignore[arg-type]

    assert fake.calls == 1
    assert results[0].new_loading_pct == 105.0
    assert results[0].loading_reduction_pct_points == 15.0
    assert results[0].classification == CandidateClassification.IMPROVED


def test_real_screening_batch_classifies_live_loading_removed() -> None:
    candidate = CandidateLine(1, "A", 2, "B", 115.0, "115", 10.0)
    model = ConductorModel("115", "test", 115.0, 1, 0.0832, 0.378, "capacitive_reactance_megaohm_mile", 0.0855, 237.03, 254.2, 314.61)
    fake = FakePowerWorld([])

    results = run_real_screening_batch(fake, [candidate], _context(model), 1)  # type: ignore[arg-type]

    assert results[0].classification == CandidateClassification.SOLVED
    assert results[0].selected_overload_removed is True


def test_real_screening_reports_tradeoff_when_selected_line_is_fixed_but_new_line_overloads() -> None:
    candidate = CandidateLine(1, "A", 2, "B", 115.0, "115", 10.0)
    model = ConductorModel("115", "test", 115.0, 1, 0.0832, 0.378, "capacitive_reactance_megaohm_mile", 0.0855, 237.03, 254.2, 314.61)
    fake = FakePowerWorld([ThermalViolation("Line C-D", 3, 4, "1", 130.0, 100.0, 130.0)])

    results = run_real_screening_batch(fake, [candidate], _context(model), 1)  # type: ignore[arg-type]

    assert results[0].classification == CandidateClassification.SOLVED_WITH_TRADEOFF
    assert results[0].selected_overload_removed is True
    assert results[0].new_loading_pct == 99.99
    assert results[0].new_thermal_violation_count == 1
    assert results[0].worst_new_thermal_violation == 130.0
