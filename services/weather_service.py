"""Retrieve current weather data from Open-Meteo."""

from __future__ import annotations

import logging
import math
from typing import Any

import requests


logger = logging.getLogger(__name__)
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def build_weather_url(latitude: float, longitude: float) -> str:
	"""Construct an Open-Meteo URL requesting current weather fields.

	The URL requests current temperature, humidity, apparent temperature, and
	precipitation. Open-Meteo selects the local timezone automatically.
	"""
	return requests.Request(
		"GET",
		OPEN_METEO_URL,
		params={
			"latitude": latitude,
			"longitude": longitude,
			"current": (
				"temperature_2m,relative_humidity_2m,precipitation,"
				"apparent_temperature"
			),
			"timezone": "auto",
		},
	).prepare().url


def validate_coordinates(latitude: float, longitude: float) -> bool:
	"""Validate latitude and longitude and raise ``ValueError`` if invalid.

	Latitude must be between -90 and 90 degrees and longitude must be between
	-180 and 180 degrees. Non-numeric and non-finite values are invalid.
	"""
	try:
		latitude_value = float(latitude)
		longitude_value = float(longitude)
	except (TypeError, ValueError) as exc:
		raise ValueError("Latitude and longitude must be numbers") from exc

	if not (
		math.isfinite(latitude_value)
		and math.isfinite(longitude_value)
		and -90 <= latitude_value <= 90
		and -180 <= longitude_value <= 180
	):
		raise ValueError("Latitude or longitude is outside its valid range")

	return True


def _number(value: Any, field_name: str) -> float:
	"""Convert a response field to a finite number."""
	if isinstance(value, bool) or value is None:
		raise ValueError(f"Missing or invalid {field_name}")
	result = float(value)
	if not math.isfinite(result):
		raise ValueError(f"Missing or invalid {field_name}")
	return result


def parse_weather_response(data: dict[str, Any]) -> dict[str, Any]:
	"""Convert an Open-Meteo current-weather response to a standard dictionary.

	The returned ``rainfall`` is the current precipitation value reported by
	Open-Meteo, measured in millimetres.
	"""
	if not isinstance(data, dict):
		raise ValueError("Open-Meteo response must be a dictionary")

	try:
		current = data["current"]
		if not isinstance(current, dict):
			raise ValueError("Open-Meteo response contains an invalid current section")

		return {
			"temperature": _number(current["temperature_2m"], "temperature"),
			"humidity": _number(current["relative_humidity_2m"], "humidity"),
			"rainfall": _number(current["precipitation"], "rainfall"),
			"apparent_temperature": _number(
				current["apparent_temperature"], "apparent temperature"
			),
			"weather_source": "open-meteo",
		}
	except (KeyError, IndexError, TypeError, ValueError) as exc:
		raise ValueError("Invalid Open-Meteo response") from exc


def _fallback_response() -> dict[str, str]:
	"""Return the stable response used when weather data is unavailable."""
	return {
		"error": "Unable to retrieve weather data",
		"weather_source": "fallback",
	}


def get_weather_data(latitude: float, longitude: float) -> dict[str, Any]:
	"""Fetch and return standardized weather data for a coordinate pair.

	Coordinates are validated, the Open-Meteo API is called with a 15-second
	timeout, and its JSON response is parsed into the service schema. Any
	validation, network, HTTP, JSON, or response-shape failure returns the
	standard fallback object instead of raising an exception.
	"""
	try:
		validate_coordinates(latitude, longitude)
	except ValueError as exc:
		logger.warning("Invalid coordinates: %s", exc)
		logger.warning("Fallback activated for invalid coordinates")
		return _fallback_response()

	try:
		url = build_weather_url(latitude, longitude)
		logger.info("Weather request started for %s, %s", latitude, longitude)
		response = requests.get(url, timeout=15)
		response.raise_for_status()
		result = parse_weather_response(response.json())
		logger.info("Weather request succeeded for %s, %s", latitude, longitude)
		return result
	except requests.Timeout:
		logger.warning("Open-Meteo request timed out")
	except requests.ConnectionError:
		logger.warning("Open-Meteo connection failed")
	except requests.HTTPError:
		logger.warning("Open-Meteo API returned an HTTP failure")
	except requests.RequestException:
		logger.warning("Open-Meteo request failed")
	except (TypeError, ValueError):
		logger.warning("Open-Meteo returned invalid JSON or weather data")

	logger.warning("Fallback activated for weather request")
	return _fallback_response()


if __name__ == "__main__":
	logging.basicConfig(level=logging.INFO)
	weather = get_weather_data(11.0168, 76.9558)
	print(weather)
