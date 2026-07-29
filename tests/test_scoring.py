from contingency_solver.analysis.scoring import ScoreWeights, score_candidate


def test_scoring_components_are_separate() -> None:
    score, components = score_candidate(10, True, 1, 104, 1, 2, 20, True, True, ScoreWeights())
    assert "loading_reduction" in components
    assert "new_thermal_violation_penalty" in components
    assert score == sum(components.values())
    assert components["overload_removed_bonus"] > 0
    assert components["line_length_penalty"] < 0
