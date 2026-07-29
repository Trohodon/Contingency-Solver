from contingency_solver.analysis.candidate_generator import CandidateGenerationSettings, generate_candidates, voltage_class
from contingency_solver.models.branch import Branch
from contingency_solver.models.bus import Bus


def _buses() -> list[Bus]:
    return [
        Bus(1, "A115", 115.0, 40.0, -82.0),
        Bus(2, "B115", 114.99, 40.05, -82.0),
        Bus(3, "C230", 230.0, 40.08, -82.0),
        Bus(4, "D230", 229.95, 40.10, -82.0),
        Bus(5, "E69", 69.0, 40.03, -82.0),
        Bus(6, "Out", 115.0, 40.04, -82.0, in_service=False),
        Bus(7, "NoCoord", 115.0, None, None),
    ]


def test_voltage_tolerance() -> None:
    assert voltage_class(114.999, 1.0) == 115.0
    assert voltage_class(228.0, 1.0) is None


def test_same_voltage_filtering_rejects_115_to_230() -> None:
    candidates, _ = generate_candidates(_buses(), [], Branch(1, 2, "1", 115.0), CandidateGenerationSettings(radius_miles=20, maximum_length_miles=20))
    pairs = {candidate.normalized_pair for candidate in candidates}
    assert (1, 3) not in pairs
    assert (2, 3) not in pairs
    assert (1, 2) in pairs
    assert (3, 4) in pairs


def test_existing_branch_rejection_and_duplicate_pair_prevention() -> None:
    candidates, _ = generate_candidates(
        _buses(),
        [Branch(2, 1, "1", 115.0)],
        Branch(1, 2, "1", 115.0),
        CandidateGenerationSettings(radius_miles=20, maximum_length_miles=20),
    )
    pairs = [candidate.normalized_pair for candidate in candidates]
    assert (1, 2) not in pairs
    assert len(pairs) == len(set(pairs))


def test_unsupported_out_of_service_and_missing_coordinates_rejected() -> None:
    candidates, _ = generate_candidates(_buses(), [], Branch(1, 2, "1", 115.0), CandidateGenerationSettings(radius_miles=20, maximum_length_miles=20))
    all_buses = {bus for candidate in candidates for bus in candidate.normalized_pair}
    assert 5 not in all_buses
    assert 6 not in all_buses
    assert 7 not in all_buses


def test_candidate_length_limits() -> None:
    candidates, _ = generate_candidates(
        _buses(),
        [],
        Branch(1, 2, "1", 115.0),
        CandidateGenerationSettings(radius_miles=20, minimum_length_miles=10, maximum_length_miles=20),
    )
    assert all(candidate.distance_miles >= 10 for candidate in candidates)
