"""LangGraph orchestration for the conversational AgriSense workflow."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from graph.state import AgriState
from services.cultivation_service import extract_required_items, generate_cultivation_plan
from services.crop_scoring_service import get_top_three_crops, rank_crop_recommendations
from services.execution_plan_service import generate_execution_plan
from services.location_service import get_coordinates, resolve_location
from services.market_service import (
    estimate_crop_profitability,
    estimate_harvest_price,
    get_current_crop_price,
    get_crop_market_summary,
    get_crop_price_trend,
)
from services.npk_estimation_service import estimate_npk
from services.procurement_service import create_procurement_plan
from services.recommendation_engine import get_top_crop_recommendation
from services.vendor_service import get_vendor_recommendations

try:
    from crop_tool import get_crop_recommendation
except ImportError:
    get_crop_recommendation = None


logger = logging.getLogger(__name__)
DEFAULT_DURATION_DAYS = 120


def _soil_fallback() -> dict[str, Any]:
    """Return usable neutral soil values when coordinates or soil data fail."""
    return {
        "ph": 6.5,
        "nitrogen": "Medium",
        "organic_carbon": "Medium",
        "sand": 35,
        "clay": 20,
        "silt": 45,
        "soil_summary": "Estimated soil characteristics",
        "source": "fallback",
    }


def _weather_fallback() -> dict[str, Any]:
    """Return usable neutral weather values when the weather service fails."""
    return {
        "temperature": 25.0,
        "humidity": 60.0,
        "rainfall": 0.0,
        "apparent_temperature": 25.0,
        "weather_source": "fallback",
    }


def _extract_crop_names(value: Any) -> list[str]:
    """Extract crop names from the crop tool's label-to-value response."""
    names: list[str] = []
    seen: set[str] = set()

    def add(candidate: Any) -> None:
        if not isinstance(candidate, str):
            return
        for item in candidate.split(","):
            name = item.strip()
            if name and name.casefold() not in seen:
                names.append(name)
                seen.add(name.casefold())

    if isinstance(value, dict):
        if isinstance(value.get("top_crop"), dict):
            add(value["top_crop"].get("crop_name"))
            for item in value.get("alternatives", []):
                if isinstance(item, dict):
                    add(item.get("crop_name"))
        else:
            for key, candidate in value.items():
                if key not in {"error", "message"}:
                    add(candidate.get("crop_name") if isinstance(candidate, dict) else candidate)
    elif isinstance(value, list):
        for item in value:
            add(item.get("crop_name") if isinstance(item, dict) else item)
    return names


def _safe_market_data(
    crop_names: list[str],
    soil: dict[str, Any],
    weather: dict[str, Any],
    farm_area_acres: float = 1.0,
) -> list[dict[str, Any]]:
    """Enrich crop names with market data and score-compatible fallbacks."""
    candidates: list[dict[str, Any]] = []
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    for crop_name in crop_names:
        try:
            current = get_current_crop_price(crop_name)
            current_price = current.get("current_price")
            if not isinstance(current_price, (int, float)):
                current_price = 0.0
            market_summary = get_crop_market_summary(crop_name)
            trend = get_crop_price_trend(crop_name)
            harvest = estimate_harvest_price(crop_name, DEFAULT_DURATION_DAYS, current_price)
            expected_price = harvest.get("expected_price", 0.0)
            if not isinstance(expected_price, (int, float)):
                expected_price = 0.0
            profitability = estimate_crop_profitability(
                crop_name=crop_name,
                current_price=current_price,
                expected_harvest_price=expected_price,
                farm_area_acres=area,
            )
            candidates.append({
                "crop_name": crop_name,
                "soil_data": soil,
                "weather_data": weather,
                "market_data": {**current, "market_summary": market_summary, **trend, **harvest},
                "current_price": current_price,
                "expected_price": expected_price,
                "profit": profitability.get("profit_per_acre", 0.0),
                "profit_per_acre": profitability.get("profit_per_acre", 0.0),
                "total_profit": profitability.get("total_profit", 0.0),
                "yield_per_acre": profitability.get("yield_per_acre", 0.0),
                "cost_per_acre": profitability.get("cost_per_acre", 0.0),
                "farm_area_acres": area,
                "suitable_for": profitability.get("suitable_for", "Suitable for farm soil"),
                "crop_profitability": profitability,
            })
        except Exception as exc:
            logger.warning("Market analysis failed for %s: %s", crop_name, exc)
            fallback_profit = estimate_crop_profitability(crop_name, farm_area_acres=area)
            candidates.append({
                "crop_name": crop_name,
                "soil_data": soil,
                "weather_data": weather,
                "market_data": {"source": "fallback"},
                "current_price": fallback_profit["expected_price"],
                "expected_price": fallback_profit["expected_price"],
                "profit": fallback_profit["profit_per_acre"],
                "profit_per_acre": fallback_profit["profit_per_acre"],
                "total_profit": fallback_profit["total_profit"],
                "yield_per_acre": fallback_profit["yield_per_acre"],
                "cost_per_acre": fallback_profit["cost_per_acre"],
                "farm_area_acres": area,
                "suitable_for": fallback_profit["suitable_for"],
                "crop_profitability": fallback_profit,
            })
    return candidates


def location_node(state: AgriState) -> dict[str, Any]:
    """Resolve location details into standardized coordinates and place names."""
    location_name = state.get("location_name")
    latitude = state.get("latitude")
    longitude = state.get("longitude")
    try:
        resolved = resolve_location(
            location_name=location_name,
            latitude=latitude,
            longitude=longitude,
        )
        return {
            "location": {
                "location": resolved["location"],
                "latitude": resolved["latitude"],
                "longitude": resolved["longitude"],
                "place_name": resolved["location_name"],
            },
            "location_name": resolved["location_name"],
            "latitude": resolved["latitude"],
            "longitude": resolved["longitude"],
        }
    except Exception as exc:
        logger.warning("Location node failed: %s", exc)
        fallback_name = location_name or "Coimbatore"
        return {
            "location": {
                "location": fallback_name,
                "latitude": latitude or 11.0168,
                "longitude": longitude or 76.9558,
            },
            "location_name": fallback_name,
            "latitude": latitude or 11.0168,
            "longitude": longitude or 76.9558,
            "error": str(exc),
        }


def soil_node(state: AgriState) -> dict[str, Any]:
    """Retrieve soil properties or write an estimated soil profile."""
    try:
        from services.soil_service import get_soil_data
        if state.get("latitude") is None or state.get("longitude") is None:
            raise ValueError("Coordinates unavailable")
        return {"soil": get_soil_data(state["latitude"], state["longitude"], state.get("location_name"))}
    except Exception as exc:
        logger.warning("Soil node failed: %s", exc)
        return {"soil": _soil_fallback(), "error": str(exc)}


def weather_node(state: AgriState) -> dict[str, Any]:
    """Retrieve weather data or write an estimated weather profile."""
    try:
        from services.weather_service import get_weather_data
        if state.get("latitude") is None or state.get("longitude") is None:
            raise ValueError("Coordinates unavailable")
        return {"weather": get_weather_data(state["latitude"], state["longitude"])}
    except Exception as exc:
        logger.warning("Weather node failed: %s", exc)
        return {"weather": _weather_fallback(), "error": str(exc)}


def npk_node(state: AgriState) -> dict[str, Any]:
    """Estimate NPK values using the existing LangChain service."""
    try:
        return {"npk": estimate_npk(state.get("soil", _soil_fallback()), state.get("weather", _weather_fallback()))}
    except Exception as exc:
        logger.warning("NPK node failed: %s", exc)
        return {"npk": {"N": 50, "P": 40, "K": 40}, "error": str(exc)}


def crop_recommendation_node(state: AgriState) -> dict[str, Any]:
    """Call the crop recommendation service and preserve a deterministic fallback."""
    try:
        if get_crop_recommendation is None:
            raise ImportError("crop_tool dependencies are unavailable")
        npk = state.get("npk", {})
        weather = state.get("weather", {})
        soil = state.get("soil", {})
        response = get_crop_recommendation(
            npk.get("N", 50), npk.get("P", 40), npk.get("K", 40),
            weather.get("temperature", 25), weather.get("humidity", 60),
            soil.get("ph", 6.5), weather.get("rainfall", 0),
        )
        names = _extract_crop_names(response)
        if names:
            return {"recommended_crops": names}
    except Exception as exc:
        logger.warning("Crop recommendation node failed: %s", exc)
    return {"recommended_crops": ["Tomato", "Onion", "Groundnut"]}


def market_analysis_node(state: AgriState) -> dict[str, Any]:
    """Collect market data and rank all recommended candidates."""
    farm_area = state.get("farm_area_acres", 1.0)
    candidates = _safe_market_data(
        state.get("recommended_crops", []),
        state.get("soil", _soil_fallback()),
        state.get("weather", _weather_fallback()),
        farm_area_acres=farm_area,
    )
    ranked = rank_crop_recommendations(candidates)
    top_three = get_top_three_crops(candidates)
    return {"market_data": top_three or ranked, "top_3_crops": top_three or ranked[:3]}


def crop_selection_node(state: AgriState) -> dict[str, Any]:
    """Pause for farmer selection, then validate the selected crop."""
    choices = state.get("market_data", [])
    names = [item.get("crop_name") for item in choices if item.get("crop_name")]
    selected = state.get("selected_crop", "").strip()
    if not selected:
        selected = interrupt({"prompt": "Which crop would you like to cultivate?", "crops": names})
    if isinstance(selected, dict):
        selected = selected.get("crop_name", "")
    selected = str(selected).strip()
    if selected.isdigit():
        selection_index = int(selected) - 1
        if 0 <= selection_index < len(names):
            selected = names[selection_index]
    for name in names:
        if name.casefold() == selected.casefold():
            return {"selected_crop": name, "awaiting_selection": False}
    return {"selected_crop": names[0] if names else "Tomato", "awaiting_selection": False}


def cultivation_node(state: AgriState) -> dict[str, Any]:
    """Generate a cultivation timeline and extract its required items."""
    crop = state.get("selected_crop", "Tomato")
    try:
        plan = generate_cultivation_plan(crop)
        return {"cultivation_plan": plan, "required_items": extract_required_items(plan)}
    except Exception as exc:
        logger.warning("Cultivation node failed: %s", exc)
        return {"cultivation_plan": {"crop_name": crop, "timeline": []}, "required_items": [], "error": str(exc)}


def procurement_node(state: AgriState) -> dict[str, Any]:
    """Create the combined procurement plan for the selected crop."""
    try:
        plan = create_procurement_plan(
            crop_name=state.get("selected_crop", "Tomato"),
            location_name=state.get("location_name", ""),
            cultivation_plan=state.get("cultivation_plan"),
            farm_area_acres=state.get("farm_area_acres", 1.0),
        )
        return {"vendors": plan, "required_items": plan.get("required_items", state.get("required_items", []))}
    except Exception as exc:
        logger.warning("Procurement node failed: %s", exc)
        return {"vendors": {"local_vendors": [], "online_vendors": []}, "error": str(exc)}


def vendor_node(state: AgriState) -> dict[str, Any]:
    """Fetch vendor recommendations and expose online links separately."""
    try:
        vendors = get_vendor_recommendations(state.get("selected_crop", "Tomato"), state.get("location_name", ""))
        online = vendors.get("online_vendors", []) if isinstance(vendors, dict) else []
        return {"vendors": {**state.get("vendors", {}), **vendors}, "online_links": online}
    except Exception as exc:
        logger.warning("Vendor node failed: %s", exc)
        return {"online_links": [], "error": str(exc)}


def final_report_node(state: AgriState) -> dict[str, Any]:
    """Assemble the complete farmer-facing report from accumulated state."""
    ranked = state.get("market_data", [])
    recommendation = get_top_crop_recommendation(ranked, state.get("soil", {}), state.get("weather", {}))
    top_crop = recommendation.get("top_crop", {})
    crop_name = state.get("selected_crop", top_crop.get("crop_name", "Tomato"))
    area = state.get("farm_area_acres", 1.0)
    profitability = estimate_crop_profitability(crop_name, farm_area_acres=area)
    report = {
        "location": state.get("location", {}),
        "soil_health": state.get("soil", {}),
        "weather_conditions": state.get("weather", {}),
        "npk_values": state.get("npk", {}),
        "farm_area_acres": area,
        "top_3_crops": state.get("top_3_crops", ranked[:3]),
        "recommended_crop": top_crop,
        "selected_crop": crop_name,
        "profit_per_acre": profitability["profit_per_acre"],
        "total_profit": profitability["total_profit"],
        "cost_breakdown": {
            "seeds": round(profitability["total_cost"] * 0.15, 2),
            "fertilizers": round(profitability["total_cost"] * 0.35, 2),
            "machinery": round(profitability["total_cost"] * 0.20, 2),
            "labor": round(profitability["total_cost"] * 0.30, 2),
            "total_cost": profitability["total_cost"],
        },
        "market_analysis": ranked,
        "expected_harvest_price": profitability["expected_price"],
        "expected_profit": profitability["total_profit"],
        "cultivation_timeline": state.get("cultivation_plan", {}).get("timeline", []),
        "required_items": state.get("required_items", []),
        "local_vendors": state.get("vendors", {}).get("local_vendors", []),
        "online_purchase_links": state.get("online_links", []),
        "final_recommendations": recommendation,
    }
    return {"final_report": report}


def build_workflow() -> Any:
    """Build and compile the interruptible AgriSense StateGraph."""
    builder = StateGraph(AgriState)
    builder.add_node("location_node", location_node)
    builder.add_node("soil_node", soil_node)
    builder.add_node("weather_node", weather_node)
    builder.add_node("npk_node", npk_node)
    builder.add_node("crop_recommendation_node", crop_recommendation_node)
    builder.add_node("market_analysis_node", market_analysis_node)
    builder.add_node("crop_selection_node", crop_selection_node)
    builder.add_node("cultivation_node", cultivation_node)
    builder.add_node("procurement_node", procurement_node)
    builder.add_node("vendor_node", vendor_node)
    builder.add_node("final_report_node", final_report_node)
    builder.add_edge(START, "location_node")
    builder.add_edge("location_node", "soil_node")
    builder.add_edge("soil_node", "weather_node")
    builder.add_edge("weather_node", "npk_node")
    builder.add_edge("npk_node", "crop_recommendation_node")
    builder.add_edge("crop_recommendation_node", "market_analysis_node")
    builder.add_edge("market_analysis_node", "crop_selection_node")
    builder.add_edge("crop_selection_node", "cultivation_node")
    builder.add_edge("cultivation_node", "procurement_node")
    builder.add_edge("procurement_node", "vendor_node")
    builder.add_edge("vendor_node", "final_report_node")
    builder.add_edge("final_report_node", END)
    return builder.compile(checkpointer=MemorySaver())


workflow = build_workflow()
