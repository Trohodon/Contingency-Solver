from dataclasses import dataclass


@dataclass(frozen=True)
class Bus:
    number: int
    name: str
    nominal_kv: float
    latitude: float | None
    longitude: float | None
    in_service: bool = True
    area: str | None = None
    zone: str | None = None
    owner: str | None = None
    substation: str | None = None

    @property
    def has_valid_coordinates(self) -> bool:
        return (
            self.latitude is not None
            and self.longitude is not None
            and -90.0 <= self.latitude <= 90.0
            and -180.0 <= self.longitude <= 180.0
        )
