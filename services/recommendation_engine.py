"""Build farmer-facing recommendations from ranked crop results."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any


logger = logging.getLogger(__name__)


def _number(value: Any, default: float = 0.0) -> float:
    """Convert a value to a finite float, returning a safe default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _price(crop_data: dict[str, Any]) -> Any:
    """Read an expected-price field from supported market result schemas."""
    return crop_data.get(
        "expected_price",
        crop_data.get("expected_harvest_price", crop_data.get("expected_price_at_harvest")),
    )


def _value(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present value among several compatible field names."""
    if not isinstance(data, dict):
        return None
    for key in keys:
        if key in data:
            return data[key]
    return None


def generate_crop_evidence(
    crop_data: dict[str, Any],
    soil_data: dict[str, Any],
    weather_data: dict[str, Any],
) -> list[str]:
    """Generate concise evidence explaining why a crop is recommended."""
    if not isinstance(crop_data, dict):
        crop_data = {}
    if not isinstance(soil_data, dict):
        soil_data = {}
    if not isinstance(weather_data, dict):
        weather_data = {}

    evidence: list[str] = []
    ph = _number(soil_data.get("ph"), default=float("nan"))
    if 6.0 <= ph <= 7.5:
        evidence.append("Soil pH is suitable")
    else:
        evidence.append("Soil pH may require adjustment")

    organic_carbon = str(soil_data.get("organic_carbon", "")).lower()
    if organic_carbon == "high":
        evidence.append("Organic carbon level is high")
    elif organic_carbon == "medium":
        evidence.append("Organic carbon level is adequate")
    else:
        evidence.append("Organic carbon level needs improvement")

    nitrogen = str(soil_data.get("nitrogen", "")).lower()
    if nitrogen in {"medium", "high"}:
        evidence.append("Nitrogen level is adequate")
    else:
        evidence.append("Nitrogen level may need supplementation")

    temperature = _number(weather_data.get("temperature"), default=float("nan"))
    humidity = _number(weather_data.get("humidity"), default=float("nan"))
    rainfall = _number(weather_data.get("rainfall"), default=float("nan"))
    if 18 <= temperature <= 35 and 30 <= humidity <= 90 and rainfall >= 0:
        evidence.append("Weather conditions support healthy growth")
    else:
        evidence.append("Weather conditions may require farm management")

    current_price = _number(crop_data.get("current_price"))
    expected_price = _number(_price(crop_data))
    if current_price > 0 and expected_price >= current_price:
        evidence.append("Expected harvest price is favorable")
    else:
        evidence.append("Expected harvest price should be monitored")
    return evidence


def generate_crop_summary(crop_data: dict[str, Any]) -> dict[str, Any]:
    """Return the farmer-facing summary fields for one scored crop."""
    if not isinstance(crop_data, dict):
        logger.warning("Invalid crop data supplied for summary")
        return {
            "crop_name": "Unknown",
            "score": 0.0,
            "current_price": 0.0,
            "expected_price": 0.0,
            "profit": 0.0,
            "profit_per_acre": 0.0,
            "total_profit": 0.0,
            "yield_per_acre": 0.0,
            "cost_per_acre": 0.0,
            "farm_area_acres": 1.0,
            "suitable_for": "Standard farm soil",
        }

    profit_val = _number(
        _value(crop_data, "profit_per_acre", "profit") or _value(crop_data.get("crop_profitability", {}), "profit_per_acre", "profit")
    )
    total_val = _number(
        _value(crop_data, "total_profit") or _value(crop_data.get("crop_profitability", {}), "total_profit") or profit_val
    )
    yield_val = _number(
        _value(crop_data, "yield_per_acre") or _value(crop_data.get("crop_profitability", {}), "yield_per_acre")
    )
    cost_val = _number(
        _value(crop_data, "cost_per_acre") or _value(crop_data.get("crop_profitability", {}), "cost_per_acre")
    )
    farm_area = _number(
        _value(crop_data, "farm_area_acres") or _value(crop_data.get("crop_profitability", {}), "farm_area_acres"), default=1.0
    )
    suitable = str(
        _value(crop_data, "suitable_for") or _value(crop_data.get("crop_profitability", {}), "suitable_for") or "Suitable for regional climate"
    )

    return {
        "crop_name": crop_data.get("crop_name", "Unknown"),
        "score": _number(crop_data.get("score")),
        "current_price": _number(crop_data.get("current_price")),
        "expected_price": _number(_price(crop_data)),
        "profit": profit_val,
        "profit_per_acre": profit_val,
        "total_profit": total_val,
        "yield_per_acre": yield_val,
        "cost_per_acre": cost_val,
        "farm_area_acres": farm_area,
        "suitable_for": suitable,
    }


def _empty_recommendation(message: str = "No crop recommendations available") -> dict[str, Any]:
    """Return a stable response when no ranked crop can be recommended."""
    return {
        "top_crop": {},
        "alternatives": [],
        "evidence": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recommendation_message": message,
    }


def build_recommendation(
    ranked_crops: list[dict[str, Any]],
    soil_data: dict[str, Any],
    weather_data: dict[str, Any],
) -> dict[str, Any]:
    """Build a complete recommendation package from descending-ranked crops."""
    if not isinstance(ranked_crops, list) or not ranked_crops:
        logger.warning("No ranked crops available for recommendation")
        return _empty_recommendation()

    valid_crops = [crop for crop in ranked_crops if isinstance(crop, dict)]
    if not valid_crops:
        logger.warning("Ranked crop results contained no valid crops")
        return _empty_recommendation()

    top_crop = generate_crop_summary(valid_crops[0])
    alternatives = [generate_crop_summary(crop) for crop in valid_crops[1:3]]
    crop_name = top_crop["crop_name"]
    message = (
        f"{crop_name} is recommended because it has the highest overall score "
        "and profitability."
    )
    return {
        "top_crop": top_crop,
        "alternatives": alternatives,
        "evidence": generate_crop_evidence(valid_crops[0], soil_data, weather_data),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "recommendation_message": message,
    }


def get_top_crop_recommendation(
    ranked_crops: list[dict[str, Any]],
    soil_data: dict[str, Any],
    weather_data: dict[str, Any],
) -> dict[str, Any]:
    """Return the complete top-crop recommendation package safely."""
    try:
        return build_recommendation(ranked_crops, soil_data, weather_data)
    except (TypeError, ValueError, KeyError) as exc:
        logger.exception("Unable to build crop recommendation: %s", exc)
        return _empty_recommendation("Unable to build crop recommendation")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_crops = [
        {
            "crop_name": "Tomato",
            "score": 89.78,
            "current_price": 2800,
            "expected_price": 3080,
            "profit": 745000,
        },
        {"crop_name": "Onion", "score": 83.20, "profit": 600000},
        {"crop_name": "Groundnut", "score": 79.10, "profit": 500000},
    ]
    sample_soil = {"ph": 6.8, "nitrogen": "Medium", "organic_carbon": "High"}
    sample_weather = {"temperature": 28, "humidity": 76, "rainfall": 120}
    print(get_top_crop_recommendation(sample_crops, sample_soil, sample_weather))
