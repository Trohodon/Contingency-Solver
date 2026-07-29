from contingency_solver.analysis.classifier import classify_candidate
from contingency_solver.models.run_result import CandidateClassification


def test_solved_without_tradeoff() -> None:
    assert classify_candidate(130, 99) == CandidateClassification.SOLVED


def test_solved_with_tradeoff() -> None:
    assert classify_candidate(130, 99, new_thermal_violation_count=1) == CandidateClassification.SOLVED_WITH_TRADEOFF


def test_improved_no_effect_and_worse() -> None:
    assert classify_candidate(130, 120) == CandidateClassification.IMPROVED
    assert classify_candidate(130, 129) == CandidateClassification.NO_EFFECT
    assert classify_candidate(130, 135) == CandidateClassification.WORSE


def test_failures() -> None:
    assert classify_candidate(130, 120, intact_solved=False) == CandidateClassification.INTACT_FAILED
    assert classify_candidate(130, 120, contingency_solved=False) == CandidateClassification.CONTINGENCY_FAILED
    assert classify_candidate(130, 120, error_message="bad") == CandidateClassification.ERROR
