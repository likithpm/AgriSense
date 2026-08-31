"""Interactive command-line AgriSense AI farmer assistant."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from graph.workflow import workflow


logger = logging.getLogger(__name__)


def _parse_location_input(value: str) -> dict[str, Any]:
    """Parse a place name, coordinate pair, or current location keyword."""
    value = value.strip()
    if value.lower() in {
        "use my current location",
        "current location",
        "gps",
        "my location",
        "use current location",
        "current",
    }:
        return {
            "latitude": 11.0168,
            "longitude": 76.9558,
            "location_name": "Current Location",
        }
    parts = [part.strip() for part in value.split(",")]
    if len(parts) == 2:
        try:
            latitude = float(parts[0])
            longitude = float(parts[1])
            if not -90 <= latitude <= 90:
                raise ValueError("Latitude must be between -90 and 90")
            if not -180 <= longitude <= 180:
                raise ValueError("Longitude must be between -180 and 180")
            return {
                "latitude": latitude,
                "longitude": longitude,
                "location_name": "User Coordinates",
            }
        except ValueError as exc:
            if "Latitude" in str(exc) or "Longitude" in str(exc):
                raise exc
    return {"location_name": value}


def _print_ranked_crops(state: dict[str, Any]) -> None:
    """Display available crop options before asking the farmer to choose."""
    print("\nTOP CROP OPTIONS")
    print("----------------")
    crops = state.get("market_data", [])
    if not crops:
        print("No scored crop options are available; the assistant will use a safe default.")
        return
    for index, crop in enumerate(crops[:3], start=1):
        print(
            f"{index}. {crop.get('crop_name', 'Unknown')} | "
            f"Score: {crop.get('score', 'Unavailable')} | "
            f"Current price: {crop.get('current_price', 'Unavailable')} | "
            f"Expected price: {crop.get('expected_price', 'Unavailable')} | "
            f"Profit: {crop.get('profit', 'Unavailable')}"
        )


def _print_report(report: dict[str, Any]) -> None:
    """Print the final farmer report in readable sections."""
    print("\n" + "=" * 60)
    print("AGRISENSE AI FARMER REPORT")
    print("=" * 60)
    for title, key in (
        ("LOCATION", "location"),
        ("SOIL HEALTH", "soil_health"),
        ("WEATHER CONDITIONS", "weather_conditions"),
        ("NPK VALUES", "npk_values"),
        ("TOP 3 CROPS", "top_3_crops"),
        ("RECOMMENDED CROP", "recommended_crop"),
        ("MARKET ANALYSIS", "market_analysis"),
        ("EXPECTED HARVEST PRICE", "expected_harvest_price"),
        ("EXPECTED PROFIT", "expected_profit"),
        ("FULL CULTIVATION TIMELINE", "cultivation_timeline"),
        ("REQUIRED ITEMS", "required_items"),
        ("LOCAL VENDORS", "local_vendors"),
        ("ONLINE PURCHASE LINKS", "online_purchase_links"),
        ("FINAL RECOMMENDATIONS", "final_recommendations"),
    ):
        print(f"\n{title}\n{'-' * len(title)}")
        print(report.get(key, "Unavailable"))


def run_conversation() -> None:
    """Run the two-turn location and crop-selection conversation."""
    print("AGRISENSE AI")
    print("Your farming assistant for soil, weather, markets, and cultivation.")
    location_input = input("\nEnter location name or latitude,longitude: ").strip()
    if not location_input:
        print("Please provide a location or coordinates.")
        return

    try:
        initial_state = _parse_location_input(location_input)
    except ValueError as exc:
        print(f"Invalid coordinates: {exc}")
        return
    config = {"configurable": {"thread_id": str(uuid4())}}
    try:
        paused_state = workflow.invoke(initial_state, config=config)
        if "__interrupt__" not in paused_state:
            _print_report(paused_state.get("final_report", paused_state))
            return

        _print_ranked_crops(paused_state)
        selected = input("\nWhich crop would you like to cultivate? ").strip()
        if not selected:
            print("No crop selected. The recommendation process was cancelled.")
            return
        final_state = workflow.invoke(Command(resume=selected), config=config)
        _print_report(final_state.get("final_report", final_state))
    except (EOFError, KeyboardInterrupt):
        print("\nConversation cancelled.")
    except Exception as exc:
        logger.exception("AgriSense conversation failed")
        print(f"Unable to complete the farm report: {exc}")


def main() -> None:
    """Configure logging and start the interactive assistant."""
    logging.basicConfig(level=logging.INFO)
    run_conversation()


if __name__ == "__main__":
    main()
