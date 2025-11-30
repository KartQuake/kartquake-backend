# app/services/google_maps.py

from __future__ import annotations

import os
from typing import Optional, Dict, Any, Tuple

import httpx

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
GMAPS_BASE = "https://maps.googleapis.com/maps/api"


class GoogleMapsConfigError(RuntimeError):
    pass


def _ensure_api_key() -> str:
    if not GOOGLE_MAPS_API_KEY:
        raise GoogleMapsConfigError(
            "GOOGLE_MAPS_API_KEY is not set. Please set it in your environment."
        )
    return GOOGLE_MAPS_API_KEY


# ---------------------------------------------------------
# Places / Text Search → lat/lng
# ---------------------------------------------------------

def find_place_lat_lng(query_text: str) -> Optional[Dict[str, Any]]:
    """
    Use Places Text Search API to find a place by text (e.g. 'Fred Meyer near 97229').

    Returns:
      {
        "place_id": str,
        "formatted_address": str,
        "lat": float,
        "lng": float
      }
    or None if not found / error.
    """
    api_key = _ensure_api_key()
    url = f"{GMAPS_BASE}/place/textsearch/json"
    params = {
        "query": query_text,
        "key": api_key,
    }

    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    results = data.get("results") or []
    if not results:
        return None

    first = results[0]
    geom = first.get("geometry", {})
    loc = geom.get("location", {})
    lat = loc.get("lat")
    lng = loc.get("lng")
    if lat is None or lng is None:
        return None

    return {
        "place_id": first.get("place_id"),
        "formatted_address": first.get("formatted_address"),
        "lat": float(lat),
        "lng": float(lng),
    }


# ---------------------------------------------------------
# Distance Matrix → drive time
# ---------------------------------------------------------

def _call_distance_matrix(
    origin: str,
    destination: str,
) -> Optional[float]:
    """
    Call Distance Matrix API with string origin/destination (address or 'lat,lng').

    Returns drive time in minutes or None.
    """
    api_key = _ensure_api_key()
    url = f"{GMAPS_BASE}/distancematrix/json"
    params = {
        "origins": origin,
        "destinations": destination,
        "mode": "driving",
        "units": "imperial",
        "key": api_key,
    }

    try:
        resp = httpx.get(url, params=params, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    rows = data.get("rows") or []
    if not rows:
        return None
    elements = rows[0].get("elements") or []
    if not elements:
        return None
    elem = elements[0]
    if elem.get("status") != "OK":
        return None

    duration_sec = elem.get("duration", {}).get("value")
    if duration_sec is None:
        return None

    minutes = float(duration_sec) / 60.0
    return minutes


def drive_time_minutes_text_to_latlng(
    origin_text: str,
    lat: float,
    lng: float,
) -> Optional[float]:
    """
    Driving time from origin_text (address/zip) to a lat,lng point.
    """
    dest = f"{lat},{lng}"
    return _call_distance_matrix(origin_text, dest)


def drive_time_minutes_latlng_to_latlng(
    o_lat: float,
    o_lng: float,
    d_lat: float,
    d_lng: float,
) -> Optional[float]:
    """
    Driving time between two lat,lng points.
    """
    origin = f"{o_lat},{o_lng}"
    dest = f"{d_lat},{d_lng}"
    return _call_distance_matrix(origin, dest)
