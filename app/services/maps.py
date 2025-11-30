import os
from typing import Tuple, Optional

import httpx


GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")


class MapsError(Exception):
    pass


async def get_distance_and_duration(
    origin: str,
    destination: str,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Call Google Distance Matrix API to get distance (km) and duration (minutes)
    between two points. origin/destination can be 'lat,lng' or addresses.

    Returns (distance_km, duration_minutes) or (None, None) on failure.
    """

    if not GOOGLE_MAPS_API_KEY:
        # No key -> gracefully fall back to None
        return None, None

    url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": destination,
        "key": GOOGLE_MAPS_API_KEY,
        "units": "metric",
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None, None

    try:
        row = data["rows"][0]
        element = row["elements"][0]
        if element.get("status") != "OK":
            return None, None

        distance_m = element["distance"]["value"]  # meters
        duration_s = element["duration"]["value"]  # seconds

        distance_km = distance_m / 1000.0
        duration_min = duration_s / 60.0
        return distance_km, duration_min
    except Exception:
        return None, None
