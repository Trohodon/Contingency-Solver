from contingency_solver.analysis.electrical import (
    base_impedance_ohms,
    calculate_line_parameters,
    ohms_to_per_unit,
    total_reactance_ohms,
    total_resistance_ohms,
)
from contingency_solver.models.conductor import ConductorModel


def test_base_impedance() -> None:
    assert base_impedance_ohms(115.0, 100.0) == 132.25


def test_ohms_to_per_unit() -> None:
    assert round(ohms_to_per_unit(13.225, 115.0, 100.0), 4) == 0.1


def test_total_impedance_values() -> None:
    assert total_resistance_ohms(0.08, 10.0) == 0.8
    assert total_reactance_ohms(0.42, 10.0) == 4.2


def test_calculate_line_parameters() -> None:
    model = ConductorModel("115", "115 test", 115.0, 1, 0.08, 0.42, "susceptance_per_mile", 0.000003, 180, 220, 260)
    params = calculate_line_parameters(model, 10.0, 100.0)
    assert round(params.r_pu, 6) == round(0.8 / 132.25, 6)
    assert params.rate_a_mva == 180
