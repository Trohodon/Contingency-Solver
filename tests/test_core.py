from contingency_solver.core import (
    Branch,
    Bus,
    CandidateLine,
    CandidateSettings,
    ConductorModel,
    CandidateClassification,
    ThermalViolation,
    VoltageViolation,
    base_impedance_ohms,
    build_branch_pair_index,
    calculate_line_parameters,
    classify_candidate,
    generate_candidates,
    haversine_miles,
    match_branches_for_issue,
    new_thermal_violations,
    new_voltage_violations,
    ohms_to_per_unit,
    preview_candidate_electricals,
    score_candidate,
    summarize_thermal_by_line,
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


def test_candidate_electrical_preview() -> None:
    candidate = CandidateLine(1, "A", 2, "B", 115, "115", 10.0)
    model = ConductorModel("115", "test", 115.0, 1, 0.08, 0.42, "susceptance_per_mile", 0.000003, 180, 220, 260)
    preview = preview_candidate_electricals(candidate, {"115": model}, 100.0)
    assert preview.validation_message == "OK"
    assert round(float(preview.r_pu), 6) == round(0.8 / 132.25, 6)
    assert preview.rate_a_mva == 180


def test_candidate_electrical_preview_reports_missing_model() -> None:
    candidate = CandidateLine(1, "A", 2, "B", 500, "500", 10.0)
    preview = preview_candidate_electricals(candidate, {}, 100.0)
    assert "No conductor model" in preview.validation_message


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


def test_summarize_thermal_by_line_groups_multiple_contingencies_on_same_issue() -> None:
    rows = [
        ThermalViolation("Bus1 - Bus2 ckt 1", 0, 0, "", 95, 100, 95, contingency="CTG1"),
        ThermalViolation("Bus1 - Bus2 ckt 1", 0, 0, "", 98, 100, 98, contingency="CTG2"),
        ThermalViolation("Bus3 - Bus4 ckt 1", 0, 0, "", 96, 100, 96, contingency="CTG3"),
    ]
    summaries = summarize_thermal_by_line(rows)
    assert [item.branch_key for item in summaries] == ["Bus1 - Bus2 ckt 1", "Bus3 - Bus4 ckt 1"]
    assert summaries[0].result_count == 2
    assert summaries[0].worst_contingency == "CTG2"
    assert summaries[0].worst_percent_loading == 98


def test_match_branches_for_issue_by_bus_numbers() -> None:
    buses = [Bus(101, "North", 115, 40, -82), Bus(102, "South", 115, 40.1, -82.1)]
    branches = [Branch(101, 102, "1", 115)]
    matches = match_branches_for_issue("Line 101 to 102 circuit 1", branches, buses)
    assert matches == branches


def test_match_branches_for_issue_by_bus_names() -> None:
    buses = [Bus(101, "North Ridge", 115, 40, -82), Bus(102, "South Tap", 115, 40.1, -82.1)]
    branches = [Branch(101, 102, "1", 115)]
    matches = match_branches_for_issue("North Ridge - South Tap", branches, buses)
    assert matches == branches


def test_match_branches_for_issue_by_powerworld_result_text() -> None:
    buses = [
        Bus(370490, "3adams T", 115, 40, -82),
        Bus(370466, "3Ritter!", 115, 40.1, -82.1),
        Bus(1, "One", 115, 41, -83),
        Bus(115, "Voltage Named Bus", 115, 41.1, -83.1),
    ]
    target = Branch(370490, 370466, "1", 115)
    branches = [target, Branch(1, 115, "1", 115)]
    index = build_branch_pair_index(branches)
    matches = match_branches_for_issue("370490 3adams T - 370466 3Ritter! ckt 1 115kv", branches, buses, index)
    assert matches == [target]


def test_match_branches_for_issue_uses_numeric_index_on_large_case() -> None:
    buses = [Bus(number, f"Bus {number}", 115, 40, -82) for number in range(1, 5002)]
    branches = [Branch(number, number + 1, "1", 115) for number in range(1, 5000)]
    target = Branch(3700, 3701, "1", 115)
    branches.append(target)
    index = build_branch_pair_index(branches)
    matches = match_branches_for_issue("3700 Bus 3700 - 3701 Bus 3701 ckt 1", branches, buses, index)
    assert matches[0] == target


def test_conductor_validation() -> None:
    model = ConductorModel("230", "bad", 230, None, None, 0.2, "susceptance_per_mile", None, None, 1, 1)
    assert validate_conductor_models({"230": model})
