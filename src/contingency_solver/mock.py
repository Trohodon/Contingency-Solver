from __future__ import annotations

import random

from contingency_solver.core import (
    Branch,
    Bus,
    CandidateLine,
    CandidateResult,
    Contingency,
    ScoreWeights,
    ThermalViolation,
    VoltageViolation,
    classify_candidate,
    score_candidate,
)


def mock_buses() -> list[Bus]:
    return [
        Bus(101, "North Ridge", 115.0, 40.000, -82.000, area="A", zone="1", owner="Utility", substation="North"),
        Bus(102, "Lake Tap", 115.0, 40.100, -82.120, area="A", zone="1", owner="Utility", substation="Lake"),
        Bus(103, "Oak Street", 114.99, 40.210, -82.020, area="A", zone="1", owner="Utility", substation="Oak"),
        Bus(104, "River Road", 115.0, 39.930, -81.850, area="A", zone="2", owner="Utility", substation="River"),
        Bus(105, "Old Mill", 115.0, 39.850, -82.240, in_service=False, area="A", zone="2", owner="Utility"),
        Bus(201, "Central 230", 230.0, 40.050, -82.300, area="A", zone="1", owner="Utility", substation="Central"),
        Bus(202, "West 230", 230.0, 40.190, -82.410, area="A", zone="1", owner="Utility", substation="West"),
        Bus(203, "South 230", 229.95, 39.780, -82.150, area="A", zone="2", owner="Utility", substation="South"),
        Bus(204, "East 230", 230.0, 40.270, -81.910, area="B", zone="3", owner="Partner", substation="East"),
        Bus(301, "Unsupported 69", 69.0, 40.070, -82.050, area="A", zone="1", owner="Utility"),
        Bus(401, "No Coordinates", 115.0, None, None, area="A", zone="1", owner="Utility"),
    ]


def mock_branches() -> list[Branch]:
    return [
        Branch(101, 102, "1", 115.0),
        Branch(102, 103, "1", 115.0),
        Branch(201, 202, "1", 230.0),
        Branch(202, 203, "1", 230.0),
        Branch(101, 104, "1", 115.0),
    ]


def mock_contingencies() -> list[Contingency]:
    return [
        Contingency("CTG_102_103_LOSS", "Thermal", False, True, 1, ["Open branch 102-103 ckt 1"]),
        Contingency("CTG_201_202_LOSS", "Thermal", False, None, 1, ["Open branch 201-202 ckt 1"]),
        Contingency("CTG_NORTH_TRANSFORMER", "Transformer", False, None, 2, ["Open transformer North T1"]),
    ]


def mock_baseline_overloads() -> list[ThermalViolation]:
    return [
        ThermalViolation("102-103-1", 102, 103, "1", 236.0, 180.0, 131.1),
        ThermalViolation("201-202-1", 201, 202, "1", 565.0, 450.0, 125.6),
    ]


def mock_voltage_violations() -> list[VoltageViolation]:
    return [VoltageViolation(104, "River Road", 0.943, 0.95, "LOW")]


def simulate_results(candidates: list[CandidateLine], original_loading_pct: float = 131.1) -> list[CandidateResult]:
    rng = random.Random(42)
    results: list[CandidateResult] = []
    weights = ScoreWeights()
    for index, candidate in enumerate(candidates, start=1):
        distance_factor = max(0.0, 1.0 - candidate.distance_miles / 70.0)
        voltage_bonus = 1.0 if candidate.nominal_kv == 115.0 else 0.75
        reduction = round(rng.uniform(-3.0, 22.0) * distance_factor * voltage_bonus, 2)
        new_loading = round(original_loading_pct - reduction, 2)
        new_thermal = 1 if rng.random() < 0.18 else 0
        new_voltage = 1 if rng.random() < 0.10 else 0
        intact_solved = rng.random() > 0.04
        contingency_solved = intact_solved and rng.random() > 0.05
        classification = classify_candidate(
            original_loading_pct,
            new_loading,
            new_thermal_violation_count=new_thermal,
            new_voltage_violation_count=new_voltage,
            intact_solved=intact_solved,
            contingency_solved=contingency_solved,
        )
        score, components = score_candidate(
            reduction,
            new_loading <= 100.0,
            new_thermal,
            104.0 if new_thermal else 0.0,
            new_voltage,
            2.5 if new_voltage else 0.0,
            candidate.distance_miles,
            intact_solved,
            contingency_solved,
            weights,
        )
        results.append(
            CandidateResult(
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
                original_loading_pct,
                new_loading,
                reduction,
                236.0,
                round(236.0 * (new_loading / original_loading_pct), 1),
                new_loading <= 100.0,
                new_thermal,
                104.0 if new_thermal else 0.0,
                new_voltage,
                0.944 if new_voltage else 0.962,
                1.043,
                intact_solved,
                contingency_solved,
                round(rng.uniform(0.8, 4.6), 2),
                "" if intact_solved and contingency_solved else "Mock solution failure injected for workflow testing.",
                components,
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    for rank, result in enumerate(results, start=1):
        result.rank = rank
    return results
