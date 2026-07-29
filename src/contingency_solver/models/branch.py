from dataclasses import dataclass


@dataclass(frozen=True)
class Branch:
    from_bus: int
    to_bus: int
    circuit_id: str = "1"
    nominal_kv: float | None = None
    in_service: bool = True

    @property
    def normalized_pair(self) -> tuple[int, int]:
        return tuple(sorted((self.from_bus, self.to_bus)))
