from dataclasses import dataclass
import json
from pathlib import Path


class SchemaResolutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PowerWorldSchema:
    raw: dict

    @classmethod
    def load(cls, path: Path) -> "PowerWorldSchema":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def alternatives(self, object_name: str, field_name: str) -> list[str]:
        return self.raw["objects"][object_name]["fields"][field_name]

    def object_type(self, object_name: str) -> str:
        return str(self.raw["objects"][object_name]["object_type"])

    def resolve_field(self, object_name: str, field_name: str, available_fields: set[str]) -> str:
        alternatives = self.alternatives(object_name, field_name)
        normalized_available = {field.lower(): field for field in available_fields}
        for candidate in alternatives:
            found = normalized_available.get(candidate.lower())
            if found is not None:
                return found
        raise SchemaResolutionError(
            f"No configured field for {object_name}.{field_name} is available. "
            f"Configured alternatives: {', '.join(alternatives)}. "
            "Update config/powerworld_schema.json after confirming the PowerWorld field name."
        )

    def resolve_fields(self, object_name: str, field_names: list[str], available_fields: set[str]) -> dict[str, str]:
        return {field_name: self.resolve_field(object_name, field_name, available_fields) for field_name in field_names}

    def resolve_optional_fields(self, object_name: str, field_names: list[str], available_fields: set[str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for field_name in field_names:
            try:
                resolved[field_name] = self.resolve_field(object_name, field_name, available_fields)
            except SchemaResolutionError:
                continue
        return resolved
