from dataclasses import dataclass, field


@dataclass(frozen=True)
class Contingency:
    name: str
    category: str = ""
    skipped: bool = False
    solved: bool | None = None
    action_count: int | None = None
    actions: list[str] = field(default_factory=list)
