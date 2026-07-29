import pytest

from contingency_solver.powerworld.schema import PowerWorldSchema, SchemaResolutionError


def test_schema_resolves_configured_alternative_case_insensitive() -> None:
    schema = PowerWorldSchema(
        {
            "objects": {
                "bus": {
                    "object_type": "Bus",
                    "fields": {"number": ["BusNum", "Number"]},
                }
            }
        }
    )
    assert schema.resolve_field("bus", "number", {"number"}) == "number"


def test_schema_refuses_unconfirmed_field() -> None:
    schema = PowerWorldSchema(
        {
            "objects": {
                "bus": {
                    "object_type": "Bus",
                    "fields": {"latitude": ["Latitude", "BusLat"]},
                }
            }
        }
    )
    with pytest.raises(SchemaResolutionError):
        schema.resolve_field("bus", "latitude", {"Lat"})
