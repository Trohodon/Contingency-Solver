from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    rlat1 = radians(lat1)
    rlat2 = radians(lat2)
    a = sin(dlat / 2.0) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_MILES * asin(sqrt(a))


def midpoint(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[float, float]:
    return ((lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0)
