"""Orchestrate AgriSense location, weather, soil, NPK, and crop services."""

from __future__ import annotations

import logging
from typing import Any

from services.location_service import get_coordinates, resolve_location
from services.npk_estimation_service import estimate_npk
from services.soil_service import get_soil_data
from services.weather_service import get_weather_data

try:
    from crop_tool import get_crop_recommendation
except ImportError:
    get_crop_recommendation = None


logger = logging.getLogger(__name__)


def _error_response(message: str) -> dict[str, Any]:
    """Create a stable response for a failed orchestration stage."""
    return {
        "location": {},
        "weather": {},
        "soil": {},
        "npk": {},
        "crop_recommendation": {},
        "error": message,
    }


def validate_weather_data(weather: dict[str, Any]) -> bool:
    """Return whether weather data contains all fields needed downstream."""
    return (
        isinstance(weather, dict)
        and weather.get("temperature") is not None
        and weather.get("humidity") is not None
        and weather.get("rainfall") is not None
    )


def validate_soil_data(soil: dict[str, Any]) -> bool:
    """Return whether soil data contains the pH value needed downstream."""
    return isinstance(soil, dict) and soil.get("ph") is not None


def get_agri_recommendation(
    location_name: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    """Return a complete agricultural recommendation for a named location or coordinates.

    Resolves location details (forward/reverse geocoding), passes coordinates
    to the weather and soil services, estimates NPK values, and requests crop recommendations.
    """
    if not location_name and (latitude is None or longitude is None):
        logger.warning("Neither location name nor coordinates supplied")
        return _error_response("Either location name or coordinates must be provided")

    logger.info("STAGE 1 START: location_service resolving (%s, %s, %s)", location_name, latitude, longitude)
    try:
        resolved = resolve_location(
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
        )
        logger.info("STAGE 1 COMPLETE: location_service resolved -> %s", resolved.get("location_name"))
    except Exception as exc:
        logger.exception("Location resolution failed for %s, (%s, %s)", location_name, latitude, longitude)
        return _error_response(f"Unable to retrieve location: {exc}")

    location = {
        "location": resolved["location"],
        "location_name": resolved["location_name"],
        "latitude": resolved["latitude"],
        "longitude": resolved["longitude"],
    }
    latitude_val = resolved["latitude"]
    longitude_val = resolved["longitude"]
    location_query = resolved["location_name"]

    result: dict[str, Any] = {
        "location": location,
        "weather": {},
        "soil": {},
        "npk": {},
        "crop_recommendation": {},
    }

    try:
        logger.info("STAGE 2 START: weather_service for %s (%s, %s)", location_query, latitude_val, longitude_val)
        weather = get_weather_data(latitude_val, longitude_val)
        result["weather"] = weather
        logger.info("STAGE 2 COMPLETE: weather_service -> temp=%s, humidity=%s, rainfall=%s", weather.get("temperature"), weather.get("humidity"), weather.get("rainfall"))
    except Exception as exc:
        logger.exception("Weather service failed for %s", location_query)
        return {**result, "error": f"Unable to retrieve weather data: {exc}"}

    try:
        logger.info("STAGE 3 START: soil_service for %s (%s, %s)", location_query, latitude_val, longitude_val)
        soil = get_soil_data(latitude_val, longitude_val, location_query)
        result["soil"] = soil
        logger.info("STAGE 3 COMPLETE: soil_service -> ph=%s, nitrogen=%s, source=%s", soil.get("ph"), soil.get("nitrogen"), soil.get("source", "gee"))
    except Exception as exc:
        logger.exception("Soil service failed for %s", location_query)
        return {**result, "error": f"Unable to retrieve soil data: {exc}"}

    if not validate_weather_data(weather) or not validate_soil_data(soil):
        logger.warning("Insufficient weather or soil data for %s", location_query)
        return {**result, "error": "Insufficient weather or soil data"}

    try:
        logger.info("STAGE 4 START: npk_estimation_service for %s", location_query)
        npk = estimate_npk(soil, weather)
        result["npk"] = npk
        logger.info("STAGE 4 COMPLETE: npk_estimation_service -> N=%s, P=%s, K=%s", npk.get("N"), npk.get("P"), npk.get("K"))
    except Exception as exc:
        logger.exception("NPK estimation failed for %s", location_query)
        return {**result, "error": f"Unable to estimate NPK values: {exc}"}

    try:
        logger.info("STAGE 5 START: crop recommendation (crop_tool) for %s", location_query)
        if get_crop_recommendation is None:
            raise ImportError("crop_tool dependencies are not installed")
        crop_recommendation = get_crop_recommendation(
            N=npk["N"],
            P=npk["P"],
            K=npk["K"],
            temperature=weather["temperature"],
            humidity=weather["humidity"],
            ph=soil["ph"],
            rainfall=weather["rainfall"],
        )
        result["crop_recommendation"] = crop_recommendation
        logger.info("STAGE 5 COMPLETE: crop recommendation -> %s", crop_recommendation)
    except Exception as exc:
        logger.warning("Crop recommendation failed for %s: %s (using fallback crop names)", location_query, exc)
        result["crop_recommendation"] = {}

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    recommendation = get_agri_recommendation("Coimbatore")
    print(recommendation)
