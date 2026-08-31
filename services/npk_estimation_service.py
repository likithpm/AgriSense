"""Estimate soil NPK requirements with Google Gemini chat model."""

from __future__ import annotations

import json
import logging
from typing import Any

from services.llm_service import extract_text_from_response, get_llm, parse_json_from_response

logger = logging.getLogger(__name__)

DEFAULT_NPK = {"N": 50, "P": 40, "K": 40}


def _parse_npk(content: Any) -> dict[str, int]:
    """Parse and validate an NPK JSON object from model output."""
    parsed = parse_json_from_response(content) if not isinstance(content, dict) else content
    if not isinstance(parsed, dict) or set(parsed) != {"N", "P", "K"}:
        raise ValueError("Model response must contain exactly N, P, and K")

    result: dict[str, int] = {}
    for nutrient in ("N", "P", "K"):
        value = parsed[nutrient]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{nutrient} must be numeric")
        result[nutrient] = int(value)
    return result


def estimate_npk(soil_data: dict[str, Any], weather_data: dict[str, Any]) -> dict[str, int]:
    """Estimate nitrogen, phosphorus, and potassium values from soil and weather data."""
    prompt = f"""
You are an agricultural soil nutrition expert.
Estimate the required soil nutrient values from the supplied data.

Soil data:
{json.dumps(soil_data, sort_keys=True)}

Weather data:
{json.dumps(weather_data, sort_keys=True)}

Return ONLY valid JSON with exactly these integer keys and no markdown:
{{"N": 80, "P": 42, "K": 45}}
""".strip()

    try:
        logger.info("Requesting NPK estimate from Google Gemini model")
        llm = get_llm()
        if llm is None:
            raise RuntimeError("Gemini LLM is not configured")
        response = llm.invoke(prompt)
        result = _parse_npk(response.content)
        logger.info("NPK estimate received successfully from Gemini: %s", result)
        return result
    except Exception:
        logger.exception("NPK estimation failed; using default nutrient values")
        return DEFAULT_NPK.copy()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sample_soil_data = {
        "ph": 6.5,
        "nitrogen": "Medium",
        "organic_carbon": "Medium",
        "sand": 35,
        "clay": 20,
        "silt": 45,
    }
    sample_weather_data = {
        "temperature": 28,
        "humidity": 76,
        "rainfall": 120,
    }
    print(estimate_npk(sample_soil_data, sample_weather_data))
