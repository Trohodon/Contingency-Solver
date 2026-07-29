from dataclasses import dataclass


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
