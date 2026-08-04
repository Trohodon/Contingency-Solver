from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from math import asin, cos, radians, sin, sqrt
import re
from typing import Any

SUPPORTED_VOLTAGES = (115.0, 230.0)
EARTH_RADIUS_MILES = 3958.7613


@dataclass(frozen=True)
class Bus:
    number: int
    name: str
    nominal_kv: float
    latitude: float | None
    longitude: float | None
    in_service: bool = True
    area: str | None = None
    zone: str | None = None
    owner: str | None = None
    substation: str | None = None

    @property
    def has_coordinates(self) -> bool:
        return (
            self.latitude is not None
            and self.longitude is not None
            and -90 <= self.latitude <= 90
            and -180 <= self.longitude <= 180
        )


@dataclass(frozen=True)
class Branch:
    from_bus: int
    to_bus: int
    circuit_id: str = "1"
    nominal_kv: float | None = None
    in_service: bool = True

    @property
    def pair(self) -> tuple[int, int]:
        return tuple(sorted((self.from_bus, self.to_bus)))


@dataclass(frozen=True)
class Contingency:
    name: str
    category: str = ""
    skipped: bool = False
    solved: bool | None = None
    action_count: int | None = None
    actions: list[str] = field(default_factory=list)


@dataclass
class ConductorModel:
    key: str
    name: str
    nominal_kv: float
    bundle_count: int | None
    resistance_ohm_per_mile: float | None
    reactance_ohm_per_mile: float | None
    charging_input_type: str
    charging_value_per_mile: float | None
    rate_a_mva: float | None
    rate_b_mva: float | None
    rate_c_mva: float | None
    circuit_count: int = 1
    notes: str = ""

    def missing_values(self) -> list[str]:
        values = {
            "bundle_count": self.bundle_count,
            "resistance_ohm_per_mile": self.resistance_ohm_per_mile,
            "reactance_ohm_per_mile": self.reactance_ohm_per_mile,
            "charging_value_per_mile": self.charging_value_per_mile,
            "rate_a_mva": self.rate_a_mva,
            "rate_b_mva": self.rate_b_mva,
            "rate_c_mva": self.rate_c_mva,
        }
        return [name for name, value in values.items() if value is None]


@dataclass(frozen=True)
class CandidateLine:
    from_bus: int
    from_bus_name: str
    to_bus: int
    to_bus_name: str
    nominal_kv: float
    conductor_key: str
    distance_miles: float

    @property
    def pair(self) -> tuple[int, int]:
        return tuple(sorted((self.from_bus, self.to_bus)))


@dataclass(frozen=True)
class ThermalViolation:
    branch_key: str
    from_bus: int
    to_bus: int
    circuit_id: str
    mva: float
    rating_mva: float
    percent_loading: float
    contingency: str = ""
    category: str = ""


@dataclass(frozen=True)
class LineLoadingSummary:
    branch_key: str
    result_count: int
    worst_contingency: str
    worst_percent_loading: float
    worst_mva: float
    worst_rating_mva: float


@dataclass(frozen=True)
class VoltageViolation:
    bus_number: int
    bus_name: str
    voltage_pu: float
    limit_pu: float
    violation_type: str


class CandidateClassification(StrEnum):
    SOLVED = "SOLVED"
    SOLVED_WITH_TRADEOFF = "SOLVED_WITH_TRADEOFF"
    IMPROVED = "IMPROVED"
    NO_EFFECT = "NO_EFFECT"
    WORSE = "WORSE"
    INTACT_FAILED = "INTACT_FAILED"
    CONTINGENCY_FAILED = "CONTINGENCY_FAILED"
    ERROR = "ERROR"


@dataclass
class CandidateResult:
    rank: int
    score: float
    classification: CandidateClassification
    from_bus: int
    from_bus_name: str
    to_bus: int
    to_bus_name: str
    nominal_kv: float
    conductor_model: str
    distance_miles: float
    original_loading_pct: float
    new_loading_pct: float
    loading_reduction_pct_points: float
    original_mva: float
    new_mva: float
    selected_overload_removed: bool
    new_thermal_violation_count: int
    worst_new_thermal_violation: float
    new_voltage_violation_count: int
    minimum_voltage: float
    maximum_voltage: float
    intact_solved: bool
    contingency_solved: bool
    runtime_seconds: float
    error_message: str = ""
    score_components: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class CandidateSettings:
    radius_miles: float = 50.0
    minimum_length_miles: float = 1.0
    maximum_length_miles: float = 50.0
    voltage_classes: tuple[float, ...] = SUPPORTED_VOLTAGES
    voltage_tolerance_kv: float = 1.0
    study_area_mode: str = "endpoints"
    maximum_candidates: int | None = 250


@dataclass(frozen=True)
class CandidateSummary:
    buses_found: int
    candidates_generated: int
    warnings: list[str]


@dataclass(frozen=True)
class LineElectricalParameters:
    resistance_ohms: float
    reactance_ohms: float
    charging_total: float
    zbase_ohms: float
    r_pu: float
    x_pu: float
    rate_a_mva: float
    rate_b_mva: float
    rate_c_mva: float


@dataclass(frozen=True)
class CandidateElectricalPreview:
    candidate: CandidateLine
    conductor_name: str
    resistance_ohms: float | None
    reactance_ohms: float | None
    r_pu: float | None
    x_pu: float | None
    rate_a_mva: float | None
    validation_message: str


@dataclass(frozen=True)
class ScoreWeights:
    loading_reduction: float = 2.0
    overload_removed_bonus: float = 35.0
    new_thermal_violation_penalty: float = 15.0
    new_voltage_violation_penalty: float = 12.0
    line_length_penalty: float = 0.2
    solution_failure_penalty: float = 100.0


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    rlat1 = radians(lat1)
    rlat2 = radians(lat2)
    a = sin(dlat / 2) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * asin(sqrt(a))


def voltage_class(nominal_kv: float, tolerance_kv: float) -> float | None:
    for supported in SUPPORTED_VOLTAGES:
        if abs(nominal_kv - supported) <= tolerance_kv:
            return supported
    return None


def generate_candidates(
    buses: list[Bus],
    branches: list[Branch],
    overloaded_branch: Branch,
    settings: CandidateSettings,
) -> tuple[list[CandidateLine], CandidateSummary]:
    bus_by_number = {bus.number: bus for bus in buses}
    end_a = bus_by_number.get(overloaded_branch.from_bus)
    end_b = bus_by_number.get(overloaded_branch.to_bus)
    if end_a is None or end_b is None or not end_a.has_coordinates or not end_b.has_coordinates:
        return [], CandidateSummary(0, 0, ["Selected branch endpoints need valid bus coordinates."])

    existing_pairs = {branch.pair for branch in branches if branch.in_service}
    study_buses: list[Bus] = []
    center_lat = (float(end_a.latitude) + float(end_b.latitude)) / 2
    center_lon = (float(end_a.longitude) + float(end_b.longitude)) / 2

    for bus in buses:
        if not bus.in_service or not bus.has_coordinates:
            continue
        cls = voltage_class(bus.nominal_kv, settings.voltage_tolerance_kv)
        if cls is None or cls not in settings.voltage_classes:
            continue
        if settings.study_area_mode == "midpoint":
            in_area = haversine_miles(float(bus.latitude), float(bus.longitude), center_lat, center_lon) <= settings.radius_miles
        else:
            in_area = (
                haversine_miles(float(bus.latitude), float(bus.longitude), float(end_a.latitude), float(end_a.longitude))
                <= settings.radius_miles
                or haversine_miles(float(bus.latitude), float(bus.longitude), float(end_b.latitude), float(end_b.longitude))
                <= settings.radius_miles
            )
        if in_area:
            study_buses.append(bus)

    candidates: list[CandidateLine] = []
    seen: set[tuple[int, int]] = set()
    for left, right in combinations(study_buses, 2):
        pair = tuple(sorted((left.number, right.number)))
        if pair in seen or pair in existing_pairs or left.number == right.number:
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
            CandidateLine(left.number, left.name, right.number, right.name, left_cls, str(int(left_cls)), distance)
        )
        if settings.maximum_candidates is not None and len(candidates) >= settings.maximum_candidates:
            break

    warnings = ["Candidate list reached the configured maximum."] if settings.maximum_candidates and len(candidates) >= settings.maximum_candidates else []
    return candidates, CandidateSummary(len(study_buses), len(candidates), warnings)


def base_impedance_ohms(nominal_kv: float, system_mva_base: float) -> float:
    return nominal_kv**2 / system_mva_base


def ohms_to_per_unit(ohms: float, nominal_kv: float, system_mva_base: float) -> float:
    return ohms / base_impedance_ohms(nominal_kv, system_mva_base)


def calculate_line_parameters(model: ConductorModel, length_miles: float, system_mva_base: float) -> LineElectricalParameters:
    missing = model.missing_values()
    if missing:
        raise ValueError(f"Conductor model '{model.name}' is missing: {', '.join(missing)}")
    resistance = float(model.resistance_ohm_per_mile) * length_miles
    reactance = float(model.reactance_ohm_per_mile) * length_miles
    charging = calculate_total_line_charging(model.charging_input_type, float(model.charging_value_per_mile), length_miles)
    zbase = base_impedance_ohms(model.nominal_kv, system_mva_base)
    return LineElectricalParameters(
        resistance,
        reactance,
        charging,
        zbase,
        resistance / zbase,
        reactance / zbase,
        float(model.rate_a_mva),
        float(model.rate_b_mva),
        float(model.rate_c_mva),
    )


def calculate_total_line_charging(charging_input_type: str, charging_value_per_mile: float, length_miles: float) -> float:
    if charging_input_type == "susceptance_per_mile":
        return charging_value_per_mile * length_miles
    if charging_input_type == "capacitive_reactance_megaohm_mile":
        if charging_value_per_mile <= 0:
            raise ValueError("Capacitive reactance must be greater than zero.")
        return (1.0 / (charging_value_per_mile * 1_000_000.0)) * length_miles
    raise ValueError(
        f"Unsupported charging input type '{charging_input_type}'. "
        "Supported values: susceptance_per_mile, capacitive_reactance_megaohm_mile."
    )


def preview_candidate_electricals(
    candidate: CandidateLine,
    conductor_models: dict[str, ConductorModel],
    system_mva_base: float,
) -> CandidateElectricalPreview:
    model = conductor_models.get(candidate.conductor_key)
    if model is None:
        return CandidateElectricalPreview(candidate, "", None, None, None, None, None, f"No conductor model for {candidate.conductor_key} kV.")
    try:
        params = calculate_line_parameters(model, candidate.distance_miles, system_mva_base)
    except ValueError as exc:
        return CandidateElectricalPreview(candidate, model.name, None, None, None, None, model.rate_a_mva, str(exc))
    return CandidateElectricalPreview(
        candidate=candidate,
        conductor_name=model.name,
        resistance_ohms=params.resistance_ohms,
        reactance_ohms=params.reactance_ohms,
        r_pu=params.r_pu,
        x_pu=params.x_pu,
        rate_a_mva=params.rate_a_mva,
        validation_message="OK",
    )


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
    tradeoff = new_thermal_violation_count > 0 or new_voltage_violation_count > 0
    if removed and not tradeoff:
        return CandidateClassification.SOLVED
    if removed and tradeoff:
        return CandidateClassification.SOLVED_WITH_TRADEOFF
    if reduction > meaningful_improvement_threshold_pct_points:
        return CandidateClassification.IMPROVED
    if abs(reduction) <= meaningful_improvement_threshold_pct_points:
        return CandidateClassification.NO_EFFECT
    return CandidateClassification.WORSE


def score_candidate(
    loading_reduction_pct_points: float,
    selected_overload_removed: bool,
    new_thermal_violation_count: int,
    worst_new_thermal_violation_pct: float,
    new_voltage_violation_count: int,
    voltage_severity: float,
    distance_miles: float,
    intact_solved: bool,
    contingency_solved: bool,
    weights: ScoreWeights,
) -> tuple[float, dict[str, float]]:
    components = {
        "loading_reduction": loading_reduction_pct_points * weights.loading_reduction,
        "overload_removed_bonus": weights.overload_removed_bonus if selected_overload_removed else 0.0,
        "new_thermal_violation_penalty": -new_thermal_violation_count * weights.new_thermal_violation_penalty,
        "thermal_severity_penalty": -max(0.0, worst_new_thermal_violation_pct - 100.0),
        "new_voltage_violation_penalty": -new_voltage_violation_count * weights.new_voltage_violation_penalty,
        "voltage_severity_penalty": -voltage_severity,
        "line_length_penalty": -distance_miles * weights.line_length_penalty,
        "solution_failure_penalty": 0.0 if intact_solved and contingency_solved else -weights.solution_failure_penalty,
    }
    return sum(components.values()), components


def new_thermal_violations(baseline: list[ThermalViolation], candidate: list[ThermalViolation]) -> list[ThermalViolation]:
    baseline_keys = {item.branch_key for item in baseline}
    return [item for item in candidate if item.branch_key not in baseline_keys]


def new_voltage_violations(baseline: list[VoltageViolation], candidate: list[VoltageViolation]) -> list[VoltageViolation]:
    baseline_keys = {(item.bus_number, item.violation_type) for item in baseline}
    return [item for item in candidate if (item.bus_number, item.violation_type) not in baseline_keys]


def summarize_thermal_by_line(violations: list[ThermalViolation]) -> list[LineLoadingSummary]:
    grouped: dict[str, list[ThermalViolation]] = {}
    for violation in violations:
        key = violation.branch_key or "(No line/transformer label)"
        grouped.setdefault(key, []).append(violation)

    summaries: list[LineLoadingSummary] = []
    for branch_key, rows in grouped.items():
        worst = max(rows, key=lambda item: item.percent_loading)
        summaries.append(
            LineLoadingSummary(
                branch_key=branch_key,
                result_count=len(rows),
                worst_contingency=worst.contingency or "(No contingency label)",
                worst_percent_loading=worst.percent_loading,
                worst_mva=worst.mva,
                worst_rating_mva=worst.rating_mva,
            )
        )
    summaries.sort(key=lambda item: item.worst_percent_loading, reverse=True)
    return summaries


def branch_display(branch: Branch, buses: list[Bus]) -> str:
    bus_by_number = {bus.number: bus for bus in buses}
    left = bus_by_number.get(branch.from_bus)
    right = bus_by_number.get(branch.to_bus)
    left_label = f"{branch.from_bus} {left.name}" if left else str(branch.from_bus)
    right_label = f"{branch.to_bus} {right.name}" if right else str(branch.to_bus)
    kv = f" {branch.nominal_kv:.0f} kV" if branch.nominal_kv else ""
    return f"{left_label} - {right_label} ckt {branch.circuit_id}{kv}"


def build_branch_pair_index(branches: list[Branch]) -> dict[tuple[int, int], list[Branch]]:
    index: dict[tuple[int, int], list[Branch]] = {}
    for branch in branches:
        index.setdefault(branch.pair, []).append(branch)
    return index


def match_branches_for_issue(
    issue_text: str,
    branches: list[Branch],
    buses: list[Bus],
    pair_index: dict[tuple[int, int], list[Branch]] | None = None,
) -> list[Branch]:
    pair_index = pair_index or build_branch_pair_index(branches)
    bus_numbers = {bus.number for bus in buses}
    circuit_id = _extract_circuit_id(issue_text)

    preferred_pair = _extract_preferred_bus_pair(issue_text, bus_numbers)
    if preferred_pair is not None:
        pair_candidates = _filter_by_circuit(pair_index.get(preferred_pair, []), circuit_id)
        if pair_candidates:
            return _rank_branch_matches(issue_text, _dedupe_branches(pair_candidates), buses)

    numbers = [int(value) for value in re.findall(r"\d+", issue_text) if int(value) in bus_numbers]

    numeric_candidates: list[Branch] = []
    for left_index, left in enumerate(numbers):
        for right in numbers[left_index + 1 :]:
            pair = tuple(sorted((left, right)))
            numeric_candidates.extend(pair_index.get(pair, []))
    if numeric_candidates:
        return _rank_branch_matches(issue_text, _filter_by_circuit(_dedupe_branches(numeric_candidates), circuit_id), buses)

    # Name matching is a fallback because it can be expensive on large cases.
    bus_by_number = {bus.number: bus for bus in buses}
    mentioned_buses = [
        bus
        for bus in buses
        if bus.name and _contains_name(_normalize_issue_text(issue_text), bus.name)
    ]
    name_candidates: list[Branch] = []
    for left_index, left in enumerate(mentioned_buses):
        for right in mentioned_buses[left_index + 1 :]:
            name_candidates.extend(pair_index.get(tuple(sorted((left.number, right.number))), []))
    if name_candidates:
        return _rank_branch_matches(issue_text, _dedupe_branches(name_candidates), buses)

    # Last-resort fuzzy matching is capped so the GUI cannot freeze on large cases.
    limited_branches = branches[:2000]
    return _rank_branch_matches(issue_text, limited_branches, buses)


def _extract_preferred_bus_pair(issue_text: str, bus_numbers: set[int]) -> tuple[int, int] | None:
    parts = re.split(r"\s+[-–—]\s+", issue_text, maxsplit=1)
    if len(parts) != 2:
        return None
    left = _first_known_bus_number(parts[0], bus_numbers)
    right = _first_known_bus_number(parts[1], bus_numbers)
    if left is None or right is None or left == right:
        return None
    return tuple(sorted((left, right)))


def _first_known_bus_number(text: str, bus_numbers: set[int]) -> int | None:
    for value in re.findall(r"\d+", text):
        number = int(value)
        if number in bus_numbers:
            return number
    return None


def _extract_circuit_id(issue_text: str) -> str | None:
    match = re.search(r"\b(?:ckt|circuit)\s+([^\s,;]+)", issue_text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().lower()


def _filter_by_circuit(branches: list[Branch], circuit_id: str | None) -> list[Branch]:
    if not circuit_id:
        return branches
    exact = [branch for branch in branches if branch.circuit_id.strip().lower() == circuit_id]
    return exact or branches


def _rank_branch_matches(issue_text: str, branches: list[Branch], buses: list[Bus]) -> list[Branch]:
    scored: list[tuple[int, Branch]] = []
    bus_by_number = {bus.number: bus for bus in buses}
    normalized_issue = _normalize_issue_text(issue_text)
    issue_numbers = set(re.findall(r"\d+", issue_text))
    for branch in branches:
        score = _branch_issue_match_score(normalized_issue, issue_numbers, branch, bus_by_number)
        if score > 0:
            scored.append((score, branch))
    scored.sort(key=lambda item: (-item[0], item[1].from_bus, item[1].to_bus, item[1].circuit_id))
    return [branch for _score, branch in scored]


def _dedupe_branches(branches: list[Branch]) -> list[Branch]:
    seen: set[tuple[int, int, str]] = set()
    output: list[Branch] = []
    for branch in branches:
        key = (branch.from_bus, branch.to_bus, branch.circuit_id)
        if key not in seen:
            seen.add(key)
            output.append(branch)
    return output


def _branch_issue_match_score(
    normalized_issue_text: str,
    issue_numbers: set[str],
    branch: Branch,
    bus_by_number: dict[int, Bus],
) -> int:
    left = bus_by_number.get(branch.from_bus)
    right = bus_by_number.get(branch.to_bus)

    score = 0
    if str(branch.from_bus) in issue_numbers and str(branch.to_bus) in issue_numbers:
        score += 100
    if left and right and _contains_name(normalized_issue_text, left.name) and _contains_name(normalized_issue_text, right.name):
        score += 80
    if branch.circuit_id and branch.circuit_id.lower() in normalized_issue_text:
        score += 10
    if score and branch.nominal_kv is not None and str(int(round(branch.nominal_kv))) in issue_numbers:
        score += 5
    return score


def _contains_name(normalized_text: str, name: str) -> bool:
    normalized_name = _normalize_issue_text(name)
    return bool(normalized_name) and normalized_name in normalized_text


def _normalize_issue_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def validate_conductor_models(models: dict[str, ConductorModel]) -> list[str]:
    errors: list[str] = []
    for key, model in models.items():
        missing = model.missing_values()
        if missing:
            errors.append(f"{key}: missing {', '.join(missing)}")
        if model.nominal_kv <= 0:
            errors.append(f"{key}: nominal kV must be positive")
        if model.circuit_count < 1:
            errors.append(f"{key}: circuit count must be at least 1")
    return errors


def result_to_row(result: CandidateResult) -> dict[str, Any]:
    return {
        "Rank": result.rank,
        "Score": result.score,
        "Classification": result.classification.value,
        "From Bus": result.from_bus,
        "From Name": result.from_bus_name,
        "To Bus": result.to_bus,
        "To Name": result.to_bus_name,
        "Nominal kV": result.nominal_kv,
        "Conductor": result.conductor_model,
        "Distance": result.distance_miles,
        "Original %": result.original_loading_pct,
        "New %": result.new_loading_pct,
        "Reduction pp": result.loading_reduction_pct_points,
        "Original MVA": result.original_mva,
        "New MVA": result.new_mva,
        "Removed": result.selected_overload_removed,
        "New Thermal": result.new_thermal_violation_count,
        "Worst New Thermal": result.worst_new_thermal_violation,
        "New Voltage": result.new_voltage_violation_count,
        "Min V": result.minimum_voltage,
        "Max V": result.maximum_voltage,
        "Intact": result.intact_solved,
        "Contingency": result.contingency_solved,
        "Runtime": result.runtime_seconds,
        "Error": result.error_message,
    }
