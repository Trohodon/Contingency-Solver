from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from itertools import combinations
from math import asin, cos, radians, sin, sqrt
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
    charging = float(model.charging_value_per_mile) * length_miles
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
