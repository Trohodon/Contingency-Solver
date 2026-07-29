from dataclasses import dataclass

from contingency_solver.models.conductor import ConductorModel


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


def total_resistance_ohms(resistance_ohm_per_mile: float, length_miles: float) -> float:
    return resistance_ohm_per_mile * length_miles


def total_reactance_ohms(reactance_ohm_per_mile: float, length_miles: float) -> float:
    return reactance_ohm_per_mile * length_miles


def total_line_charging(charging_value_per_mile: float, length_miles: float) -> float:
    return charging_value_per_mile * length_miles


def base_impedance_ohms(nominal_kv: float, system_mva_base: float) -> float:
    return nominal_kv**2 / system_mva_base


def ohms_to_per_unit(ohms: float, nominal_kv: float, system_mva_base: float) -> float:
    return ohms / base_impedance_ohms(nominal_kv, system_mva_base)


def calculate_line_parameters(
    model: ConductorModel,
    length_miles: float,
    system_mva_base: float,
) -> LineElectricalParameters:
    missing = model.missing_required_fields()
    if missing:
        raise ValueError(f"Conductor model '{model.name}' is missing: {', '.join(missing)}")

    r_ohms = total_resistance_ohms(float(model.resistance_ohm_per_mile), length_miles)
    x_ohms = total_reactance_ohms(float(model.reactance_ohm_per_mile), length_miles)
    charging = total_line_charging(float(model.charging_value_per_mile), length_miles)
    zbase = base_impedance_ohms(model.nominal_kv, system_mva_base)
    return LineElectricalParameters(
        resistance_ohms=r_ohms,
        reactance_ohms=x_ohms,
        charging_total=charging,
        zbase_ohms=zbase,
        r_pu=r_ohms / zbase,
        x_pu=x_ohms / zbase,
        rate_a_mva=float(model.rate_a_mva),
        rate_b_mva=float(model.rate_b_mva),
        rate_c_mva=float(model.rate_c_mva),
    )
