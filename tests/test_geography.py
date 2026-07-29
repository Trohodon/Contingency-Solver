from contingency_solver.analysis.geography import haversine_miles


def test_haversine_distance_columbus_to_cleveland() -> None:
    distance = haversine_miles(39.9612, -82.9988, 41.4993, -81.6944)
    assert 120.0 <= distance <= 130.0


def test_haversine_zero_distance() -> None:
    assert haversine_miles(40.0, -82.0, 40.0, -82.0) == 0.0
