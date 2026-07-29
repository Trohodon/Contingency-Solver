from contingency_solver.models.conductor import ConductorModel
from contingency_solver.utilities.validation import validate_conductor_models


def test_conductor_validation_requires_values() -> None:
    model = ConductorModel("230", "bad", 230, None, None, 0.2, "susceptance_per_mile", None, None, 1, 1)
    errors = validate_conductor_models({"230": model})
    assert errors
