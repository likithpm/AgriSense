"""Location service for forward and reverse geocoding using OpenStreetMap / Nominatim."""

from __future__ import annotations

import logging
from typing import Any
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderServiceError, GeocoderTimedOut

logger = logging.getLogger(__name__)

USER_AGENT = "agrisense_ai_geocoder"
DEFAULT_TIMEOUT = 10


def _get_geolocator() -> Nominatim:
    """Instantiate a Nominatim geolocator client."""
    return Nominatim(user_agent=USER_AGENT, timeout=DEFAULT_TIMEOUT)


def _extract_short_name(raw: dict[str, Any], fallback_address: str) -> str:
    """Extract a concise human-readable place name (e.g., 'City, State') from raw Nominatim data."""
    if not isinstance(raw, dict):
        return fallback_address.split(",")[0].strip() if fallback_address else "Unknown"

    address_parts = raw.get("address", {})
    if not isinstance(address_parts, dict):
        return fallback_address.split(",")[0].strip() if fallback_address else "Unknown"

    # Hierarchy of local place names
    local_name = (
        address_parts.get("city")
        or address_parts.get("town")
        or address_parts.get("village")
        or address_parts.get("suburb")
        or address_parts.get("county")
        or address_parts.get("state_district")
    )
    state = address_parts.get("state")

    if local_name and state:
        return f"{local_name}, {state}"
    if local_name:
        return str(local_name)
    if state:
        return str(state)

    # Fallback to the first couple elements of the formatted address
    parts = [p.strip() for p in fallback_address.split(",") if p.strip()]
    if len(parts) >= 2:
        return f"{parts[0]}, {parts[1]}"
    return parts[0] if parts else fallback_address


def get_coordinates(location: str) -> dict[str, Any] | None:
    """Forward geocode a place name into latitude and longitude coordinates."""
    if not location or not isinstance(location, str) or not location.strip():
        return None

    query = location.strip()
    try:
        geolocator = _get_geolocator()
        result = geolocator.geocode(query, addressdetails=True)
        if not result:
            logger.warning("No geocoding result found for: %s", query)
            return None

        raw = getattr(result, "raw", {})
        short_name = _extract_short_name(raw, result.address)

        return {
            "location": result.address,
            "location_name": short_name,
            "latitude": float(result.latitude),
            "longitude": float(result.longitude),
            "raw": raw,
        }
    except (GeocoderTimedOut, GeocoderServiceError) as exc:
        logger.warning("Geocoding service error for '%s': %s", query, exc)
        return None
    except Exception as exc:
        logger.exception("Unexpected error during geocoding '%s': %s", query, exc)
        return None


def get_location_from_coordinates(latitude: float, longitude: float) -> dict[str, Any] | None:
    """Reverse geocode latitude and longitude coordinates into a human-readable location."""
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        logger.warning("Invalid coordinate values: lat=%s, lon=%s (%s)", latitude, longitude, exc)
        return None

    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        logger.warning("Coordinates out of range: lat=%s, lon=%s", lat, lon)
        return None

    try:
        geolocator = _get_geolocator()
        result = geolocator.reverse((lat, lon), exactly_one=True, addressdetails=True)
        if not result:
            logger.warning("Reverse geocoding returned no result for (%s, %s)", lat, lon)
            return {
                "location": f"Coordinates ({lat:.4f}, {lon:.4f})",
                "location_name": f"{lat:.4f}, {lon:.4f}",
                "latitude": lat,
                "longitude": lon,
            }

        raw = getattr(result, "raw", {})
        short_name = _extract_short_name(raw, result.address)

        return {
            "location": result.address,
            "location_name": short_name,
            "latitude": lat,
            "longitude": lon,
            "raw": raw,
        }
    except (GeocoderTimedOut, GeocoderServiceError) as exc:
        logger.warning("Reverse geocoding service error for (%s, %s): %s", lat, lon, exc)
        return {
            "location": f"Coordinates ({lat:.4f}, {lon:.4f})",
            "location_name": f"{lat:.4f}, {lon:.4f}",
            "latitude": lat,
            "longitude": lon,
        }
    except Exception as exc:
        logger.exception("Unexpected error reverse geocoding (%s, %s): %s", lat, lon, exc)
        return {
            "location": f"Coordinates ({lat:.4f}, {lon:.4f})",
            "location_name": f"{lat:.4f}, {lon:.4f}",
            "latitude": lat,
            "longitude": lon,
        }


def resolve_location(
    location_name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """Resolve location details from either place name, coordinates, or both.

    Returns a standardized dictionary:
    {
        "location": full address or coordinate string,
        "location_name": concise place name or place query,
        "latitude": float,
        "longitude": float
    }
    """
    # Case 1: Coordinates provided
    if latitude is not None and longitude is not None:
        try:
            lat = float(latitude)
            lon = float(longitude)
            is_placeholder = (
                not location_name
                or location_name.strip().lower() in {
                    "",
                    "user coordinates",
                    "current location",
                    "my location",
                    "gps location",
                    "custom coordinates",
                }
            )
            if is_placeholder:
                reverse_info = get_location_from_coordinates(lat, lon)
                if reverse_info:
                    return {
                        "location": reverse_info["location"],
                        "location_name": reverse_info["location_name"],
                        "latitude": lat,
                        "longitude": lon,
                    }
                return {
                    "location": f"Coordinates ({lat:.4f}, {lon:.4f})",
                    "location_name": f"{lat:.4f}, {lon:.4f}",
                    "latitude": lat,
                    "longitude": lon,
                }
            # Location name is already provided alongside coordinates
            return {
                "location": location_name.strip(),
                "location_name": location_name.strip(),
                "latitude": lat,
                "longitude": lon,
            }
        except (TypeError, ValueError) as exc:
            logger.warning("Invalid coordinates in resolve_location: %s", exc)

    # Case 2: Location name provided
    if location_name and isinstance(location_name, str) and location_name.strip():
        query = location_name.strip()
        forward_info = get_coordinates(query)
        if forward_info:
            return {
                "location": forward_info["location"],
                "location_name": forward_info.get("location_name", query),
                "latitude": forward_info["latitude"],
                "longitude": forward_info["longitude"],
            }
        # Fallback when geocoding fails
        logger.warning("Could not geocode '%s'; using fallback coordinates", query)
        return {
            "location": query,
            "location_name": query,
            "latitude": 11.0168,  # Default region fallback (e.g. Coimbatore)
            "longitude": 76.9558,
        }

    # Case 3: Neither provided
    return {
        "location": "Coimbatore, Tamil Nadu",
        "location_name": "Coimbatore",
        "latitude": 11.0168,
        "longitude": 76.9558,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing forward geocoding for 'Pollachi, Tamil Nadu':")
    print(get_coordinates("Pollachi, Tamil Nadu"))
    print("\nTesting reverse geocoding for (10.6627, 76.8895):")
    print(get_location_from_coordinates(10.6627, 76.8895))
    print("\nTesting resolve_location with coords:")
    print(resolve_location(latitude=11.0168, longitude=76.9558))