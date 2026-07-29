from contingency_solver.models.conductor import ConductorModel


def validate_conductor_models(models: dict[str, ConductorModel]) -> list[str]:
    errors: list[str] = []
    for key, model in models.items():
        missing = model.missing_required_fields()
        if missing:
            errors.append(f"{key}: missing {', '.join(missing)}")
        if model.nominal_kv <= 0:
            errors.append(f"{key}: nominal kV must be positive")
        if model.circuit_count < 1:
            errors.append(f"{key}: circuit count must be at least 1")
    return errors
