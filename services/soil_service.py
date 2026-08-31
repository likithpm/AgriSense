"""Retrieve and summarize SoilGrids properties through Google Earth Engine."""

from __future__ import annotations

from typing import Any

try:
	import ee
except ImportError:  # Keep existing callers usable before earthengine-api is installed.
	ee = None


DEFAULT_DEPTH = "0-5cm"
SOILGRIDS_ASSETS = {
	"phh2o": "projects/soilgrids-isric/soilgrids_250m_2020_0-5cm_mean_phh2o",
	"nitrogen": "projects/soilgrids-isric/soilgrids_250m_2020_0-5cm_mean_nitrogen",
	"soc": "projects/soilgrids-isric/soilgrids_250m_2020_0-5cm_mean_soc",
	"sand": "projects/soilgrids-isric/soilgrids_250m_2020_0-5cm_mean_sand",
	"clay": "projects/soilgrids-isric/soilgrids_250m_2020_0-5cm_mean_clay",
	"silt": "projects/soilgrids-isric/soilgrids_250m_2020_0-5cm_mean_silt",
}
ESTIMATED_SOIL_TYPES = {
	"coimbatore": "Red Loamy",
	"chennai": "Coastal Sandy",
	"madurai": "Red Soil",
	"thanjavur": "Alluvial",
}


def _classify_level(value: float, low: float, high: float) -> str:
	"""Classify a numeric soil value using simple agronomic bands."""
	if value < low:
		return "Low"
	if value > high:
		return "High"
	return "Medium"


def _soil_summary(ph: float, nitrogen: str, organic_carbon: str) -> str:
	"""Create a short recommendation from the main soil indicators."""
	if 6.0 <= ph <= 7.5 and nitrogen != "Low" and organic_carbon != "Low":
		return "Suitable for vegetables"
	if ph < 5.5:
		return "Acidic soil; consider lime application"
	if ph > 8.0:
		return "Alkaline soil; consider soil amendments"
	return "Needs soil improvement"


def _extract_mean(data: dict[str, Any], property_name: str) -> float:
	"""Extract the requested property's mean value from a SoilGrids response."""
	layers = data.get("properties", {}).get("layers", [])
	for layer in layers:
		if layer.get("name") != property_name:
			continue
		depths = layer.get("depths", [])
		if not depths:
			break
		mean = depths[0].get("values", {}).get("mean")
		if mean is None:
			break
		return float(mean)
	raise ValueError(f"SoilGrids response did not contain '{property_name}'")


def _estimated_soil_data(location_name: str | None) -> dict[str, Any]:
	"""Return a conservative local estimate when SoilGrids cannot be reached."""
	location = (location_name or "").strip().lower()
	soil_type = next(
		(soil_type for city, soil_type in ESTIMATED_SOIL_TYPES.items() if city in location),
		"Unknown",
	)

	return {
		"ph": 6.5,
		"nitrogen": "Medium",
		"organic_carbon": "Medium",
		"sand": 35,
		"clay": 20,
		"silt": 45,
		"soil_summary": "Estimated soil characteristics",
		"soil_type": soil_type,
		"source": "estimated",
	}


def initialize_earth_engine() -> None:
	"""Initialize Earth Engine using the local or service-account credentials.

	Authentication is intentionally not started interactively here. Run
	``earthengine authenticate`` once for a local account, or configure service
	account credentials before starting the application.
	"""
	if ee is None:
		raise RuntimeError(
			"Google Earth Engine SDK is not installed; install earthengine-api"
		)

	try:
		# Initialization loads the credentials prepared by ``earthengine authenticate``.
		ee.Initialize()
	except Exception as exc:
		raise RuntimeError("Google Earth Engine authentication or initialization failed") from exc


def _get_gee_soil_data(latitude: float, longitude: float) -> dict[str, Any]:
	"""Read the six SoilGrids properties from the 250 m pixel at a point."""
	initialize_earth_engine()
	point = ee.Geometry.Point([longitude, latitude])
	values: dict[str, float] = {}

	for property_name, asset_id in SOILGRIDS_ASSETS.items():
		image = ee.Image(asset_id)
		# reduceRegion extracts the value of the pixel containing the supplied point.
		pixel = image.reduceRegion(
			reducer=ee.Reducer.first(),
			geometry=point,
			scale=250,
			bestEffort=True,
		).getInfo()
		if not pixel:
			raise ValueError(f"No SoilGrids pixel value found for '{property_name}'")
		value = next(iter(pixel.values()), None)
		if value is None:
			raise ValueError(f"SoilGrids pixel value for '{property_name}' is empty")
		values[property_name] = float(value)

	# SoilGrids stores pH as pH x 10, nitrogen as cg/kg, organic carbon as
	# dg/kg, and texture as g/kg. These conversions match the former REST path.
	ph = round(values["phh2o"] / 10, 1)
	nitrogen_value = values["nitrogen"] / 1000
	organic_carbon_value = values["soc"] / 10
	sand = round(values["sand"] / 10)
	clay = round(values["clay"] / 10)
	silt = round(values["silt"] / 10)
	nitrogen = _classify_level(nitrogen_value, low=0.15, high=0.30)
	organic_carbon = _classify_level(organic_carbon_value, low=10, high=20)

	return {
		"ph": ph,
		"nitrogen": nitrogen,
		"organic_carbon": organic_carbon,
		"sand": sand,
		"clay": clay,
		"silt": silt,
		"soil_summary": _soil_summary(ph, nitrogen, organic_carbon),
	}


def get_soil_data(
	latitude: float,
	longitude: float,
	location_name: str | None = None,
) -> dict[str, Any]:
	"""Return topsoil properties, falling back to local estimates if GEE fails."""
	try:
		latitude = float(latitude)
		longitude = float(longitude)
	except (TypeError, ValueError) as exc:
		return {"error": "Latitude and longitude must be numbers"}

	if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
		return {"error": "Latitude or longitude is outside its valid range"}

	try:
		return _get_gee_soil_data(latitude, longitude)
	except Exception:
		return _estimated_soil_data(location_name)


if __name__ == "__main__":
	print(get_soil_data(10.6627, 76.8895))
