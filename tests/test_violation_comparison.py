from contingency_solver.analysis.violation_comparison import new_thermal_violations, new_voltage_violations
from contingency_solver.models.violation import ThermalViolation, VoltageViolation


def test_new_thermal_violations() -> None:
    baseline = [ThermalViolation("1-2-1", 1, 2, "1", 110, 100, 110)]
    candidate = baseline + [ThermalViolation("2-3-1", 2, 3, "1", 120, 100, 120)]
    assert [item.branch_key for item in new_thermal_violations(baseline, candidate)] == ["2-3-1"]


def test_new_voltage_violations() -> None:
    baseline = [VoltageViolation(1, "A", 0.94, 0.95, "LOW")]
    candidate = baseline + [VoltageViolation(2, "B", 1.06, 1.05, "HIGH")]
    assert [item.bus_number for item in new_voltage_violations(baseline, candidate)] == [2]
