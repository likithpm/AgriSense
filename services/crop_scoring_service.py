"""Score and rank crops using soil, weather, market, and profit signals."""

from __future__ import annotations

import logging
import math
from typing import Any


logger = logging.getLogger(__name__)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    """Keep a score within the supported 0-to-100 range."""
    return max(minimum, min(maximum, value))


def _number(value: Any, default: float = 0.0) -> float:
    """Convert a value to a finite float, returning a default when invalid."""
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _value(data: dict[str, Any], *keys: str) -> Any:
    """Return the first present value among several compatible field names."""
    for key in keys:
        if key in data:
            return data[key]
    return None


def calculate_soil_score(soil_data: dict[str, Any]) -> float:
    """Calculate a 0-to-100 soil suitability score from soil properties.

    Soil near pH 6.75 receives the highest pH score. High organic carbon and
    medium or high nitrogen add bonuses to the resulting suitability score.
    """
    if not isinstance(soil_data, dict):
        logger.warning("Invalid soil data supplied for scoring")
        return 0.0

    ph = _number(soil_data.get("ph"), default=float("nan"))
    if not math.isfinite(ph):
        return 0.0
    if 6.0 <= ph <= 7.5:
        ph_score = 85.0
    else:
        ph_score = _clamp(85.0 - abs(ph - 6.75) * 20.0)

    score = ph_score
    if str(soil_data.get("organic_carbon", "")).lower() == "high":
        score += 10.0
    elif str(soil_data.get("organic_carbon", "")).lower() == "medium":
        score += 5.0
    if str(soil_data.get("nitrogen", "")).lower() in {"medium", "high"}:
        score += 5.0
    return round(_clamp(score), 2)


def calculate_weather_score(weather_data: dict[str, Any]) -> float:
    """Calculate a 0-to-100 weather suitability score.

    The score uses broad crop-friendly ranges: 20-30 degrees Celsius,
    40-80 percent humidity, and 50-200 millimetres of rainfall.
    """
    if not isinstance(weather_data, dict):
        logger.warning("Invalid weather data supplied for scoring")
        return 0.0

    temperature = _number(weather_data.get("temperature"), default=float("nan"))
    humidity = _number(weather_data.get("humidity"), default=float("nan"))
    rainfall = _number(weather_data.get("rainfall"), default=float("nan"))
    if not all(math.isfinite(value) for value in (temperature, humidity, rainfall)):
        return 0.0

    temperature_score = _clamp(100.0 - abs(temperature - 25.0) * 8.0)
    humidity_score = _clamp(100.0 - abs(humidity - 60.0) * 2.0)
    rainfall_score = 100.0 if 50.0 <= rainfall <= 200.0 else _clamp(
        100.0 - min(abs(rainfall - 50.0), abs(rainfall - 200.0)) * 0.5
    )
    return round(
        0.4 * temperature_score + 0.3 * humidity_score + 0.3 * rainfall_score,
        2,
    )


def calculate_market_score(market_data: dict[str, Any]) -> float:
    """Calculate a 0-to-100 market score from current and harvest prices."""
    if not isinstance(market_data, dict):
        logger.warning("Invalid market data supplied for scoring")
        return 0.0

    current_price = _number(
        _value(market_data, "current_price", "current_price_per_kg"),
    )
    expected_price = _number(
        _value(market_data, "expected_price", "expected_harvest_price", "expected_price_at_harvest"),
    )
    if current_price <= 0 or expected_price < 0:
        return 0.0

    change_ratio = expected_price / current_price
    return round(_clamp(50.0 + (change_ratio - 1.0) * 500.0), 2)


def calculate_profit_score(crop_profitability: dict[str, Any]) -> float:
    """Calculate a 0-to-100 profit score, capped at one million currency units."""
    if not isinstance(crop_profitability, dict):
        logger.warning("Invalid profitability data supplied for scoring")
        return 0.0
    profit = _number(crop_profitability.get("profit", crop_profitability.get("expected_profit")))
    return round(_clamp(profit / 1_000_000.0 * 100.0), 2)


def calculate_crop_score(
    soil_score: float,
    weather_score: float,
    market_score: float,
    profit_score: float,
) -> float:
    """Combine component scores using 30%, 20%, 25%, and 25% weights."""
    return round(
        _clamp(
            0.30 * _number(soil_score)
            + 0.20 * _number(weather_score)
            + 0.25 * _number(market_score)
            + 0.25 * _number(profit_score)
        ),
        2,
    )


def _score_crop(crop: dict[str, Any]) -> dict[str, Any]:
    """Calculate and format one crop recommendation."""
    soil_data = crop.get("soil_data", crop.get("soil", {}))
    weather_data = crop.get("weather_data", crop.get("weather", {}))
    market_data = crop.get("market_data", crop)
    profitability = crop.get("crop_profitability", crop.get("profitability", crop))

    score = calculate_crop_score(
        calculate_soil_score(soil_data),
        calculate_weather_score(weather_data),
        calculate_market_score(market_data),
        calculate_profit_score(profitability),
    )
    
    profit_per_acre = _number(
        _value(profitability, "profit_per_acre", "profit") or _value(crop, "profit_per_acre", "profit")
    )
    total_profit = _number(
        _value(profitability, "total_profit") or _value(crop, "total_profit") or profit_per_acre
    )
    yield_per_acre = _number(
        _value(profitability, "yield_per_acre") or _value(crop, "yield_per_acre")
    )
    cost_per_acre = _number(
        _value(profitability, "cost_per_acre") or _value(crop, "cost_per_acre")
    )
    farm_area = _number(
        _value(profitability, "farm_area_acres") or _value(crop, "farm_area_acres"), default=1.0
    )
    suitable_for = str(
        _value(profitability, "suitable_for") or _value(crop, "suitable_for") or "Suitable for local conditions"
    )

    return {
        "crop_name": crop.get("crop_name", "Unknown"),
        "score": score,
        "profit": profit_per_acre,
        "profit_per_acre": profit_per_acre,
        "total_profit": total_profit,
        "yield_per_acre": yield_per_acre,
        "cost_per_acre": cost_per_acre,
        "farm_area_acres": farm_area,
        "suitable_for": suitable_for,
        "current_price": _number(
            _value(crop, "current_price", "current_price_per_kg")
        ),
        "expected_price": _number(
            _value(crop, "expected_price", "expected_harvest_price", "expected_price_at_harvest")
        ),
    }


def rank_crop_recommendations(crop_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return valid crop results sorted by descending final score."""
    if not isinstance(crop_results, list):
        logger.warning("Invalid crop results supplied for ranking")
        return []

    scored: list[dict[str, Any]] = []
    for crop in crop_results:
        if isinstance(crop, dict):
            scored.append(_score_crop(crop))
        else:
            logger.warning("Skipping non-dictionary crop result")
    return sorted(scored, key=lambda crop: crop["score"], reverse=True)


def get_top_three_crops(crop_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return up to the three highest-scoring crop recommendations."""
    return rank_crop_recommendations(crop_results)[:3]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_crops = [
        {
            "crop_name": "Tomato",
            "soil_data": {"ph": 6.8, "nitrogen": "Medium", "organic_carbon": "High"},
            "weather_data": {"temperature": 28, "humidity": 76, "rainfall": 120},
            "current_price": 28,
            "expected_price": 32,
            "profit": 745000,
        }
    ]
    print(get_top_three_crops(sample_crops))
