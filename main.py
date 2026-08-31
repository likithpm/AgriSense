"""Console entry point for the AgriSense agricultural recommendation workflow."""

from __future__ import annotations

import logging
from typing import Any

from services.farm_advisor_service import create_farm_plan
from services.recommendation_engine import generate_crop_evidence


logger = logging.getLogger(__name__)


def _display_value(value: Any, suffix: str = "") -> str:
    """Format a value for readable console output."""
    if value is None or value == "":
        return "Unavailable"
    return f"{value}{suffix}"


def _print_section(title: str) -> None:
    """Print a consistent console section header."""
    print(f"\n{title}")
    print("-" * len(title))


def _print_weather(weather: dict[str, Any]) -> None:
    """Display weather values or a friendly missing-data message."""
    _print_section("WEATHER")
    if not weather or "error" in weather:
        print("Weather data is currently unavailable.")
        return
    print(f"Temperature: {_display_value(weather.get('temperature'), ' C')}")
    print(f"Humidity: {_display_value(weather.get('humidity'), '%')}")
    print(f"Rainfall: {_display_value(weather.get('rainfall'), ' mm')}")
    print(
        "Apparent temperature: "
        f"{_display_value(weather.get('apparent_temperature'), ' C')}"
    )


def _print_soil(soil: dict[str, Any]) -> None:
    """Display the soil profile or a friendly missing-data message."""
    _print_section("SOIL PROFILE")
    if not soil or "ph" not in soil:
        print("Soil data is currently unavailable.")
        return
    for key, label, suffix in (
        ("ph", "pH", ""),
        ("nitrogen", "Nitrogen", ""),
        ("organic_carbon", "Organic Carbon", ""),
        ("sand", "Sand", "%"),
        ("clay", "Clay", "%"),
        ("silt", "Silt", "%"),
        ("soil_type", "Soil Type", ""),
    ):
        if key in soil:
            print(f"{label}: {_display_value(soil[key], suffix)}")


def _print_npk(npk: dict[str, Any]) -> None:
    """Display the estimated nitrogen, phosphorus, and potassium values."""
    _print_section("NPK ESTIMATE")
    if not npk:
        print("NPK estimate is currently unavailable.")
        return
    for nutrient in ("N", "P", "K"):
        print(f"{nutrient}: {_display_value(npk.get(nutrient))}")


def _print_crop_recommendation(recommendation: Any) -> None:
    """Display top and alternative crops from either supported response shape."""
    _print_section("RECOMMENDED CROP")
    if not recommendation:
        print("Crop recommendation is currently unavailable.")
        return

    if isinstance(recommendation, dict) and "top_crop" in recommendation:
        top_crop = recommendation.get("top_crop") or {}
        print(top_crop.get("crop_name", "Unavailable"))
        if top_crop:
            print(f"Score: {_display_value(top_crop.get('score'))}")
            print(f"Profit: {_display_value(top_crop.get('profit'))}")

        _print_section("ALTERNATIVES")
        alternatives = recommendation.get("alternatives", [])
        if alternatives:
            for index, crop in enumerate(alternatives, start=1):
                print(f"{index}. {crop.get('crop_name', 'Unavailable')}")
                if "score" in crop:
                    print(f"   Score: {crop['score']}")
        else:
            print("No alternative crops available.")

        _print_section("EVIDENCE")
        evidence = recommendation.get("evidence", [])
        if evidence:
            for item in evidence:
                print(f"- {item}")
        else:
            print("No supporting evidence available.")
        if recommendation.get("recommendation_message"):
            print(f"\n{recommendation['recommendation_message']}")
        return

    if isinstance(recommendation, dict):
        for crop_name, details in recommendation.items():
            print(f"{crop_name}: {details}")
    elif isinstance(recommendation, list):
        for index, crop in enumerate(recommendation, start=1):
            print(f"{index}. {crop}")
    else:
        print(str(recommendation))


def _print_farm_plan(result: dict[str, Any], location: str) -> None:
    """Display the complete farm plan returned by the advisor service."""
    _print_section("LOCATION")
    location_data = result.get("location") or {}
    print(f"Name: {location_data.get('location', location)}")
    print(f"Latitude: {_display_value(location_data.get('latitude'))}")
    print(f"Longitude: {_display_value(location_data.get('longitude'))}")

    _print_weather(result.get("weather") or {})
    _print_soil(result.get("soil") or {})
    _print_npk(result.get("npk") or {})

    _print_section("RANKED CROPS")
    ranked_crops = result.get("ranked_crops") or []
    if ranked_crops:
        for index, crop in enumerate(ranked_crops, start=1):
            print(f"{index}. Crop Name: {_display_value(crop.get('crop_name'))}")
            print(f"   Score: {_display_value(crop.get('score'))}")
            print(f"   Profit: {_display_value(crop.get('profit'))}")
    else:
        print("Ranked crop data is currently unavailable.")

    _print_section("TOP CROP")
    top_crop = result.get("recommended_crop") or {}
    if top_crop:
        print(f"Crop Name: {_display_value(top_crop.get('crop_name'))}")
        print(f"Score: {_display_value(top_crop.get('score'))}")
        print(f"Profit: {_display_value(top_crop.get('profit'))}")
        print(f"Expected Harvest Price: {_display_value(top_crop.get('expected_price'))}")
    else:
        print("No top crop recommendation available.")

    _print_section("ALTERNATIVES")
    alternatives = result.get("alternatives") or []
    if alternatives:
        for index, crop in enumerate(alternatives, start=1):
            print(f"{index}. {crop.get('crop_name', 'Unavailable')}")
            print(f"   Score: {_display_value(crop.get('score'))}")
    else:
        print("No alternative crops available.")

    _print_section("MARKET SUMMARY")
    market = result.get("market_summary") or {}
    print(f"Current Price: {_display_value(market.get('current_price'))}")
    print(f"Expected Price: {_display_value(market.get('expected_price'))}")
    print(f"Trend: {_display_value(market.get('trend'))}")
    print(f"Source: {_display_value(market.get('source'))}")

    _print_section("EVIDENCE")
    evidence = result.get("evidence", [])
    if not evidence and top_crop:
        evidence = generate_crop_evidence(top_crop, result.get("soil", {}), result.get("weather", {}))
    if evidence:
        for item in evidence:
            print(f"- {item}")
    else:
        print("No supporting evidence available.")

    _print_section("EXECUTION PLAN")
    execution_plan = result.get("execution_plan") or []
    if execution_plan:
        for task in execution_plan:
            print(
                f"Day {task.get('day', 'Unavailable')}: "
                f"{task.get('task', 'Unavailable')} - "
                f"{task.get('description', 'No description available')}"
            )
    else:
        print("Execution plan is currently unavailable.")

    procurement_plan = result.get("procurement_plan") or {}
    _print_section("REQUIRED ITEMS")
    required_items = procurement_plan.get("required_items") or []
    if required_items:
        for index, item in enumerate(required_items, start=1):
            if isinstance(item, dict):
                print(
                    f"{index}. {_display_value(item.get('item'))} "
                    f"(Quantity: {_display_value(item.get('quantity'))})"
                )
            else:
                print(f"{index}. {_display_value(item)}")
    else:
        print("Required items are currently unavailable.")

    _print_section("LOCAL VENDORS")
    local_vendors = procurement_plan.get("local_vendors") or []
    if local_vendors:
        for index, vendor in enumerate(local_vendors, start=1):
            print(f"{index}. Vendor Name: {_display_value(vendor.get('name'))}")
            print(f"   Address: {_display_value(vendor.get('address'))}")
            print(f"   Rating: {_display_value(vendor.get('rating'))}")
            print(
                "   Maps Link: "
                f"{_display_value(vendor.get('search_url', vendor.get('maps_link')))}"
            )
    else:
        print("Local vendor data is currently unavailable.")

    _print_section("ONLINE VENDORS")
    online_vendors = procurement_plan.get("online_vendors") or []
    if online_vendors:
        for index, vendor in enumerate(online_vendors, start=1):
            print(f"{index}. Vendor Name: {_display_value(vendor.get('vendor_name'))}")
            print(f"   URL: {_display_value(vendor.get('website', vendor.get('url')))}")
    else:
        print("Online vendor data is currently unavailable.")


"""Compatibility entry point for the conversational AgriSense assistant.

The interactive latitude/longitude or location-name input flow lives in
``agri_chatbot.py``; this module keeps ``python main.py`` as the launcher.
"""

from agri_chatbot import main


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()