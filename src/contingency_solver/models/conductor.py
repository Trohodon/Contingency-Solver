from dataclasses import dataclass


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

    def missing_required_fields(self) -> list[str]:
        required = {
            "bundle_count": self.bundle_count,
            "resistance_ohm_per_mile": self.resistance_ohm_per_mile,
            "reactance_ohm_per_mile": self.reactance_ohm_per_mile,
            "charging_value_per_mile": self.charging_value_per_mile,
            "rate_a_mva": self.rate_a_mva,
            "rate_b_mva": self.rate_b_mva,
            "rate_c_mva": self.rate_c_mva,
        }
        return [name for name, value in required.items() if value is None]
