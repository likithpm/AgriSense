"""Build a two-stage farm plan from AgriSense recommendations and market data."""

from __future__ import annotations

import logging
from typing import Any

from services.agrisense_service import get_agri_recommendation
from services.crop_scoring_service import (
    get_top_three_crops as score_top_three_crops,
    rank_crop_recommendations,
)
from services.cultivation_service import generate_cultivation_plan
from services.execution_plan_service import generate_execution_plan
from services.market_service import (
    estimate_crop_profitability,
    estimate_harvest_price,
    get_current_crop_price,
    get_crop_market_summary,
    get_crop_price_trend,
)
from services.procurement_service import create_procurement_plan
from services.recommendation_engine import get_top_crop_recommendation

logger = logging.getLogger(__name__)
DEFAULT_DURATION_DAYS = 120


def extract_crop_names(crop_recommendation: Any) -> list[str]:
    """Extract unique crop names from recommendation values."""
    names: list[str] = []
    normalized_names: set[str] = set()

    def add(value: Any) -> None:
        if not isinstance(value, str):
            return
        for item in value.split(","):
            crop_name = item.strip()
            normalized_name = crop_name.casefold()
            if crop_name and normalized_name not in normalized_names:
                names.append(crop_name)
                normalized_names.add(normalized_name)

    if isinstance(crop_recommendation, dict):
        if isinstance(crop_recommendation.get("top_crop"), dict):
            add(crop_recommendation["top_crop"].get("crop_name"))
            for crop in crop_recommendation.get("alternatives", []):
                if isinstance(crop, dict):
                    add(crop.get("crop_name"))
        else:
            for key, value in crop_recommendation.items():
                if key in {"error", "message"}:
                    continue
                if isinstance(value, dict):
                    add(value.get("crop_name"))
                else:
                    add(value)
    elif isinstance(crop_recommendation, list):
        for item in crop_recommendation:
            if isinstance(item, dict):
                add(item.get("crop_name"))
            else:
                add(item)
    return names


def generate_market_data(crop_names: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch current price, trend, and harvest estimate for each crop."""
    market_data: dict[str, dict[str, Any]] = {}
    for crop_name in crop_names:
        try:
            current = get_current_crop_price(crop_name)
            if current.get("current_price") is None:
                market_data[crop_name] = {
                    "current_price": 0.0,
                    "expected_price": 0.0,
                    "trend": "stable",
                    "source": "fallback",
                    "error": "No market price found",
                }
                continue
            market_summary = get_crop_market_summary(crop_name, current_price_data=current)
            trend = get_crop_price_trend(crop_name)
            harvest = estimate_harvest_price(crop_name, DEFAULT_DURATION_DAYS, current["current_price"])
            expected_price = current.get("expected_price")
            if expected_price is None:
                expected_price = harvest["expected_price"]
            market_data[crop_name] = {
                **current,
                "market_summary": market_summary,
                **trend,
                **harvest,
                "expected_price": expected_price,
            }
        except Exception as exc:
            logger.exception("Market data failed for %s", crop_name)
            market_data[crop_name] = {
                "current_price": 0.0,
                "expected_price": 0.0,
                "trend": "stable",
                "source": "fallback",
                "error": str(exc),
            }
    return market_data


def build_crop_candidates(
    crop_names: list[str],
    soil_data: dict[str, Any],
    weather_data: dict[str, Any],
    market_data: dict[str, dict[str, Any]],
    farm_area_acres: float = 1.0,
) -> list[dict[str, Any]]:
    """Build scoring candidates from shared soil, weather, market, and profit data."""
    candidates: list[dict[str, Any]] = []
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    for crop_name in crop_names:
        market = market_data.get(crop_name, {})
        current_price = market.get("current_price", 0.0)
        expected_price = market.get("expected_price", 0.0)
        if current_price is None:
            current_price = 0.0
        if expected_price is None:
            expected_price = 0.0
        if current_price == 0.0 or expected_price == 0.0:
            logger.info("Using fallback market data for %s", crop_name)
            
        profitability = estimate_crop_profitability(
            crop_name=crop_name,
            current_price=current_price,
            expected_harvest_price=expected_price,
            farm_area_acres=area,
        )
        candidates.append({
            "crop_name": crop_name,
            "soil_data": soil_data,
            "weather_data": weather_data,
            "market_data": market,
            "current_price": current_price,
            "expected_price": expected_price,
            "profit": profitability["profit_per_acre"],
            "profit_per_acre": profitability["profit_per_acre"],
            "total_profit": profitability["total_profit"],
            "yield_per_acre": profitability["yield_per_acre"],
            "cost_per_acre": profitability["cost_per_acre"],
            "farm_area_acres": area,
            "suitable_for": profitability["suitable_for"],
            "crop_profitability": profitability,
        })
    return candidates


# =========================================================================
# STAGE 1: FARM ANALYSIS
# Performs ONLY Weather, Soil, NPK, Market Analysis, and Crop Scoring.
# Saves tokens by deferring cultivation and vendor generation.
# =========================================================================
def analyze_farm(
    location_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    farm_area_acres: float = 1.0,
) -> dict[str, Any]:
    """Stage 1: Analyze location, soil, weather, NPK, and score top 3 crops.
    
    Does NOT generate cultivation plan, procurement plan, or vendor search.
    """
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    empty: dict[str, Any] = {
        "location": {},
        "weather": {},
        "soil": {},
        "npk": {},
        "farm_area_acres": area,
        "top_3_crops": [],
        "ranked_crops": [],
        "market_data": {},
    }
    logger.info("ANALYZE FARM: STARTING STAGE 1 FARM ANALYSIS for (%s, %s)", latitude, longitude)
    try:
        agricultural_data = get_agri_recommendation(
            location_name=location_name.strip() if location_name else None,
            latitude=latitude,
            longitude=longitude,
        )
    except Exception as exc:
        logger.exception("Stage 1 farm analysis failed")
        return {**empty, "error": f"Unable to analyze farm: {exc}"}

    if not isinstance(agricultural_data, dict):
        return {**empty, "error": "Invalid agricultural recommendation"}

    result = {key: agricultural_data.get(key, {}) for key in ("location", "weather", "soil", "npk")}
    crop_recommendation = agricultural_data.get("crop_recommendation", {})
    crop_names = extract_crop_names(crop_recommendation)
    if not crop_names:
        crop_names = ["Tomato", "Onion", "Groundnut", "Papaya", "Cotton", "Maize"]

    logger.info("STAGE 6 START: market_service for crops %s", crop_names)
    market_data = generate_market_data(crop_names)
    logger.info("STAGE 6 COMPLETE: market_service fetched %d crops", len(market_data))

    logger.info("STAGE 7 START: crop_scoring_service scoring candidates")
    candidates = build_crop_candidates(
        crop_names,
        result["soil"],
        result["weather"],
        market_data,
        farm_area_acres=area,
    )
    ranked = rank_crop_recommendations(candidates)
    top_three = score_top_three_crops(candidates)
    logger.info("STAGE 7 COMPLETE: crop_scoring_service ranked %d crops", len(ranked))

    logger.info("STAGE 8 START: top_3_generation")
    # Format the top 3 crop cards cleanly
    formatted_top_3: list[dict[str, Any]] = []
    for crop in top_three:
        c_name = crop.get("crop_name", "Unknown")
        c_profit = estimate_crop_profitability(
            crop_name=c_name,
            current_price=crop.get("current_price", 0.0),
            expected_harvest_price=crop.get("expected_price", 0.0),
            farm_area_acres=area,
        )
        formatted_top_3.append({
            "crop_name": c_name,
            "score": round(float(crop.get("score", 75.0)), 1),
            "current_price": float(crop.get("current_price", c_profit["expected_price"])),
            "expected_price": float(crop.get("expected_price", c_profit["expected_price"])),
            "profit_per_acre": float(c_profit["profit_per_acre"]),
            "total_profit": float(c_profit["total_profit"]),
            "yield_per_acre": float(c_profit["yield_per_acre"]),
            "cost_per_acre": float(c_profit["cost_per_acre"]),
            "farm_area_acres": area,
            "suitable_for": c_profit["suitable_for"],
        })
    logger.info("STAGE 8 COMPLETE: top_3_generation -> %s", [c["crop_name"] for c in formatted_top_3])

    logger.info("ANALYZE FARM: COMPLETED STAGE 1 FARM ANALYSIS")

    return {
        **result,
        "farm_area_acres": area,
        "top_3_crops": formatted_top_3,
        "ranked_crops": ranked,
        "market_data": market_data,
    }


# =========================================================================
# STAGE 2: SELECTED CROP DETAILED PLAN
# Generates detailed cultivation timeline, scaled procurement, vendors, and
# cost/profit breakdown ONLY for the chosen crop.
# =========================================================================
def generate_crop_detailed_plan(
    selected_crop: str,
    location_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    farm_area_acres: float = 1.0,
    soil_data: dict[str, Any] | None = None,
    weather_data: dict[str, Any] | None = None,
    market_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage 2: Generate detailed cultivation, procurement, vendor, and financial plan for the selected crop."""
    if not selected_crop or not str(selected_crop).strip():
        raise ValueError("A valid selected_crop must be provided")

    crop_name = str(selected_crop).strip()
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    loc_display = location_name or "Farmland Region"

    # 1. Financial Breakdown & Profit Projections
    crop_market = (market_data or {}).get(crop_name, {})
    profit_info = estimate_crop_profitability(
        crop_name=crop_name,
        current_price=crop_market.get("current_price", 0.0),
        expected_harvest_price=crop_market.get("expected_price", 0.0),
        farm_area_acres=area,
    )

    cost_breakdown = {
        "seeds_cost": round(profit_info["total_cost"] * 0.15, 2),
        "fertilizer_soil_cost": round(profit_info["total_cost"] * 0.35, 2),
        "machinery_irrigation_cost": round(profit_info["total_cost"] * 0.20, 2),
        "labor_operations_cost": round(profit_info["total_cost"] * 0.30, 2),
        "total_cost": profit_info["total_cost"],
    }

    # 2. Cultivation Plan & 120-Day Timeline (Gemini LLM)
    logger.info("Generating Stage 2 cultivation plan for %s", crop_name)
    cultivation_plan = generate_cultivation_plan(crop_name)
    timeline_entries = cultivation_plan.get("timeline", [])
    
    # Format execution plan table
    execution_plan: list[dict[str, Any]] = []
    for item in timeline_entries:
        day = item.get("day", 1)
        stage = item.get("stage", "Cultivation")
        activities = item.get("activities", [])
        act_text = "; ".join(activities) if isinstance(activities, list) else str(activities)
        execution_plan.append({
            "day": day,
            "stage": stage,
            "task": f"Day {day}: {stage}",
            "description": act_text,
        })
    if not execution_plan:
        execution_plan = generate_execution_plan(crop_name, DEFAULT_DURATION_DAYS)

    # 3. Scaled Procurement Plan & Vendors
    logger.info("Generating Stage 2 procurement and vendor plan for %s in %s", crop_name, loc_display)
    procurement_plan = create_procurement_plan(
        crop_name=crop_name,
        location_name=loc_display,
        cultivation_plan=cultivation_plan,
        farm_area_acres=area,
    )

    # 4. Agronomic Evidence & Advice
    evidence: list[str] = [
        f"**Crop Suitability:** {profit_info['suitable_for']}.",
        f"**Expected Harvest Output:** {round(profit_info['yield_per_acre'] * area, 1)} Quintals over {area} Acre{'s' if area != 1 else ''}.",
        f"**Revenue Potential:** ₹ {profit_info['total_revenue']:,.2f} at expected market price of ₹ {profit_info['expected_price']:,.2f}/quintal.",
        f"**Estimated Net Profit:** ₹ {profit_info['total_profit']:,.2f} after estimated input costs of ₹ {profit_info['total_cost']:,.2f}.",
    ]
    if soil_data and soil_data.get("ph"):
        evidence.append(f"**Soil Compatibility:** pH {soil_data['ph']} is favorable for {crop_name} root nutrient absorption.")
    if weather_data and weather_data.get("temperature"):
        evidence.append(f"**Climate Compatibility:** Regional temperature of {weather_data['temperature']}°C supports optimal growth cycles.")

    return {
        "selected_crop": crop_name,
        "farm_area_acres": area,
        "location_name": loc_display,
        "profitability": profit_info,
        "cost_breakdown": cost_breakdown,
        "cultivation_plan": cultivation_plan,
        "execution_plan": execution_plan,
        "procurement_plan": procurement_plan,
        "local_vendors": procurement_plan.get("local_vendors", []),
        "online_vendors": procurement_plan.get("online_vendors", []),
        "evidence": evidence,
        "market_summary": {
            "current_price": profit_info["expected_price"],
            "expected_price": profit_info["expected_price"],
            "trend": crop_market.get("trend", "stable"),
            "source": crop_market.get("source", "market_intelligence"),
        },
    }


# =========================================================================
# BACKWARD-COMPATIBLE FULL PIPELINE
# Chained execution of Stage 1 + Stage 2
# =========================================================================
def create_farm_plan(
    location_name: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    farm_area_acres: float = 1.0,
    selected_crop: str | None = None,
) -> dict[str, Any]:
    """Generate complete recommendations, market analysis, and cultivation plan."""
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    stage1 = analyze_farm(
        location_name=location_name,
        latitude=latitude,
        longitude=longitude,
        farm_area_acres=area,
    )
    if stage1.get("error"):
        return stage1

    chosen_crop = selected_crop
    if not chosen_crop and stage1.get("top_3_crops"):
        chosen_crop = stage1["top_3_crops"][0]["crop_name"]
    if not chosen_crop:
        chosen_crop = "Tomato"

    loc_name = (
        stage1.get("location", {}).get("location_name")
        or stage1.get("location", {}).get("location")
        or location_name
        or "Farmland"
    )

    stage2 = generate_crop_detailed_plan(
        selected_crop=chosen_crop,
        location_name=loc_name,
        latitude=latitude,
        longitude=longitude,
        farm_area_acres=area,
        soil_data=stage1.get("soil"),
        weather_data=stage1.get("weather"),
        market_data=stage1.get("market_data"),
    )

    top_crop_summary = stage1["top_3_crops"][0] if stage1.get("top_3_crops") else {}
    alternatives = stage1["top_3_crops"][1:] if len(stage1.get("top_3_crops", [])) > 1 else []

    return {
        **stage1,
        "selected_crop": chosen_crop,
        "recommended_crop": top_crop_summary,
        "alternatives": alternatives,
        "top_3_crops": stage1.get("top_3_crops", []),
        "execution_plan": stage2.get("execution_plan", []),
        "procurement_plan": stage2.get("procurement_plan", {}),
        "cost_breakdown": stage2.get("cost_breakdown", {}),
        "evidence": stage2.get("evidence", []),
        "market_summary": stage2.get("market_summary", {}),
        "cultivation_plan": stage2.get("cultivation_plan", {}),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Testing Stage 1 analyze_farm:")
    res1 = analyze_farm("Coimbatore", farm_area_acres=1.5)
    print("Stage 1 Top 3 Crops:", res1.get("top_3_crops"))
