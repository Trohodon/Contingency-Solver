from dataclasses import dataclass


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
    def normalized_pair(self) -> tuple[int, int]:
        return tuple(sorted((self.from_bus, self.to_bus)))
