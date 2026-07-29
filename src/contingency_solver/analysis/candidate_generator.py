from dataclasses import dataclass
from itertools import combinations

from contingency_solver.analysis.geography import haversine_miles, midpoint
from contingency_solver.constants import SUPPORTED_VOLTAGE_CLASSES
from contingency_solver.models.branch import Branch
from contingency_solver.models.bus import Bus
from contingency_solver.models.candidate import CandidateLine


@dataclass(frozen=True)
class CandidateGenerationSettings:
    radius_miles: float = 50.0
    minimum_length_miles: float = 1.0
    maximum_length_miles: float = 50.0
    voltage_classes: tuple[float, ...] = SUPPORTED_VOLTAGE_CLASSES
    voltage_tolerance_kv: float = 1.0
    study_area_mode: str = "endpoints"
    maximum_candidates: int | None = 250


@dataclass(frozen=True)
class CandidateGenerationSummary:
    buses_found: int
    candidates_generated: int
    warnings: list[str]


def voltage_class(nominal_kv: float, tolerance_kv: float) -> float | None:
    for supported in SUPPORTED_VOLTAGE_CLASSES:
        if abs(nominal_kv - supported) <= tolerance_kv:
            return supported
    return None


def _existing_pairs(branches: list[Branch]) -> set[tuple[int, int]]:
    return {branch.normalized_pair for branch in branches if branch.in_service}


def _within_endpoint_area(bus: Bus, end_a: Bus, end_b: Bus, radius_miles: float) -> bool:
    assert bus.latitude is not None and bus.longitude is not None
    assert end_a.latitude is not None and end_a.longitude is not None
    assert end_b.latitude is not None and end_b.longitude is not None
    return (
        haversine_miles(bus.latitude, bus.longitude, end_a.latitude, end_a.longitude) <= radius_miles
        or haversine_miles(bus.latitude, bus.longitude, end_b.latitude, end_b.longitude) <= radius_miles
    )


def _within_midpoint_area(bus: Bus, end_a: Bus, end_b: Bus, radius_miles: float) -> bool:
    assert bus.latitude is not None and bus.longitude is not None
    assert end_a.latitude is not None and end_a.longitude is not None
    assert end_b.latitude is not None and end_b.longitude is not None
    lat, lon = midpoint(end_a.latitude, end_a.longitude, end_b.latitude, end_b.longitude)
    return haversine_miles(bus.latitude, bus.longitude, lat, lon) <= radius_miles


def generate_candidates(
    buses: list[Bus],
    branches: list[Branch],
    overloaded_branch: Branch,
    settings: CandidateGenerationSettings,
) -> tuple[list[CandidateLine], CandidateGenerationSummary]:
    bus_by_number = {bus.number: bus for bus in buses}
    end_a = bus_by_number.get(overloaded_branch.from_bus)
    end_b = bus_by_number.get(overloaded_branch.to_bus)
    if end_a is None or end_b is None:
        return [], CandidateGenerationSummary(0, 0, ["Selected branch endpoint is missing from bus data."])
    if not end_a.has_valid_coordinates or not end_b.has_valid_coordinates:
        return [], CandidateGenerationSummary(0, 0, ["Selected branch endpoints need valid latitude/longitude."])

    existing = _existing_pairs(branches)
    study_buses: list[Bus] = []
    for bus in buses:
        if not bus.in_service or not bus.has_valid_coordinates:
            continue
        cls = voltage_class(bus.nominal_kv, settings.voltage_tolerance_kv)
        if cls is None or cls not in settings.voltage_classes:
            continue
        if settings.study_area_mode == "midpoint":
            in_area = _within_midpoint_area(bus, end_a, end_b, settings.radius_miles)
        else:
            in_area = _within_endpoint_area(bus, end_a, end_b, settings.radius_miles)
        if in_area:
            study_buses.append(bus)

    candidates: list[CandidateLine] = []
    seen: set[tuple[int, int]] = set()
    for left, right in combinations(study_buses, 2):
        pair = tuple(sorted((left.number, right.number)))
        if pair in seen or pair in existing or left.number == right.number:
            continue
        left_cls = voltage_class(left.nominal_kv, settings.voltage_tolerance_kv)
        right_cls = voltage_class(right.nominal_kv, settings.voltage_tolerance_kv)
        if left_cls is None or right_cls is None or left_cls != right_cls:
            continue
        distance = haversine_miles(float(left.latitude), float(left.longitude), float(right.latitude), float(right.longitude))
        if distance < settings.minimum_length_miles or distance > settings.maximum_length_miles:
            continue
        seen.add(pair)
        candidates.append(
            CandidateLine(
                from_bus=left.number,
                from_bus_name=left.name,
                to_bus=right.number,
                to_bus_name=right.name,
                nominal_kv=left_cls,
                conductor_key=str(int(left_cls)),
                distance_miles=distance,
            )
        )
        if settings.maximum_candidates is not None and len(candidates) >= settings.maximum_candidates:
            break

    warnings = []
    if settings.maximum_candidates is not None and len(candidates) >= settings.maximum_candidates:
        warnings.append("Candidate list reached the configured maximum.")
    return candidates, CandidateGenerationSummary(len(study_buses), len(candidates), warnings)
