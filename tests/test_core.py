from contingency_solver.core import (
    Branch,
    Bus,
    CandidateSettings,
    ConductorModel,
    CandidateClassification,
    ThermalViolation,
    VoltageViolation,
    base_impedance_ohms,
    calculate_line_parameters,
    classify_candidate,
    generate_candidates,
    haversine_miles,
    new_thermal_violations,
    new_voltage_violations,
    ohms_to_per_unit,
    score_candidate,
    ScoreWeights,
    validate_conductor_models,
    voltage_class,
)


def test_haversine_distance() -> None:
    distance = haversine_miles(39.9612, -82.9988, 41.4993, -81.6944)
    assert 120 <= distance <= 130


def test_voltage_tolerance() -> None:
    assert voltage_class(114.999, 1.0) == 115.0
    assert voltage_class(228.0, 1.0) is None


def test_candidate_generation_rejects_bad_pairs() -> None:
    buses = [
        Bus(1, "A115", 115.0, 40.0, -82.0),
        Bus(2, "B115", 114.99, 40.05, -82.0),
        Bus(3, "C230", 230.0, 40.08, -82.0),
        Bus(4, "D230", 229.95, 40.10, -82.0),
        Bus(5, "E69", 69.0, 40.03, -82.0),
        Bus(6, "Out", 115.0, 40.04, -82.0, in_service=False),
        Bus(7, "NoCoord", 115.0, None, None),
    ]
    candidates, _ = generate_candidates(
        buses,
        [Branch(2, 1, "1", 115.0)],
        Branch(1, 2, "1", 115.0),
        CandidateSettings(radius_miles=20, maximum_length_miles=20),
    )
    pairs = {candidate.pair for candidate in candidates}
    assert (1, 2) not in pairs
    assert (1, 3) not in pairs
    assert (3, 4) in pairs
    all_buses = {bus for pair in pairs for bus in pair}
    assert 5 not in all_buses
    assert 6 not in all_buses
    assert 7 not in all_buses


def test_candidate_length_limits() -> None:
    buses = [Bus(1, "A", 115, 40, -82), Bus(2, "B", 115, 40.02, -82), Bus(3, "C", 115, 40.2, -82)]
    candidates, _ = generate_candidates(
        buses,
        [],
        Branch(1, 2),
        CandidateSettings(radius_miles=20, minimum_length_miles=10, maximum_length_miles=20),
    )
    assert all(candidate.distance_miles >= 10 for candidate in candidates)


def test_electrical_calculations() -> None:
    assert base_impedance_ohms(115.0, 100.0) == 132.25
    assert round(ohms_to_per_unit(13.225, 115.0, 100.0), 4) == 0.1
    model = ConductorModel("115", "test", 115.0, 1, 0.08, 0.42, "susceptance_per_mile", 0.000003, 180, 220, 260)
    params = calculate_line_parameters(model, 10.0, 100.0)
    assert round(params.r_pu, 6) == round(0.8 / 132.25, 6)


def test_classification_rules() -> None:
    assert classify_candidate(130, 99) == CandidateClassification.SOLVED
    assert classify_candidate(130, 99, new_thermal_violation_count=1) == CandidateClassification.SOLVED_WITH_TRADEOFF
    assert classify_candidate(130, 120) == CandidateClassification.IMPROVED
    assert classify_candidate(130, 129) == CandidateClassification.NO_EFFECT
    assert classify_candidate(130, 135) == CandidateClassification.WORSE
    assert classify_candidate(130, 120, intact_solved=False) == CandidateClassification.INTACT_FAILED


def test_scoring_components() -> None:
    score, components = score_candidate(10, True, 1, 104, 1, 2, 20, True, True, ScoreWeights())
    assert score == sum(components.values())
    assert components["overload_removed_bonus"] > 0
    assert components["line_length_penalty"] < 0


def test_violation_comparison() -> None:
    thermal_base = [ThermalViolation("1-2-1", 1, 2, "1", 110, 100, 110)]
    thermal_candidate = thermal_base + [ThermalViolation("2-3-1", 2, 3, "1", 120, 100, 120)]
    assert [item.branch_key for item in new_thermal_violations(thermal_base, thermal_candidate)] == ["2-3-1"]
    voltage_base = [VoltageViolation(1, "A", 0.94, 0.95, "LOW")]
    voltage_candidate = voltage_base + [VoltageViolation(2, "B", 1.06, 1.05, "HIGH")]
    assert [item.bus_number for item in new_voltage_violations(voltage_base, voltage_candidate)] == [2]


def test_conductor_validation() -> None:
    model = ConductorModel("230", "bad", 230, None, None, 0.2, "susceptance_per_mile", None, None, 1, 1)
    assert validate_conductor_models({"230": model})
