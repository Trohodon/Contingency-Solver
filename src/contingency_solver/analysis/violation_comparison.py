from contingency_solver.models.violation import ThermalViolation, VoltageViolation


def new_thermal_violations(
    baseline: list[ThermalViolation],
    candidate: list[ThermalViolation],
) -> list[ThermalViolation]:
    baseline_keys = {item.branch_key for item in baseline}
    return [item for item in candidate if item.branch_key not in baseline_keys]


def new_voltage_violations(
    baseline: list[VoltageViolation],
    candidate: list[VoltageViolation],
) -> list[VoltageViolation]:
    baseline_keys = {(item.bus_number, item.violation_type) for item in baseline}
    return [item for item in candidate if (item.bus_number, item.violation_type) not in baseline_keys]
