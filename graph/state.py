"""Typed state shared by the AgriSense LangGraph workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class AgriState(TypedDict, total=False):
    """State carried between AgriSense workflow nodes."""

    location_name: str
    latitude: float
    longitude: float
    farm_area_acres: float
    location: dict[str, Any]
    soil: dict[str, Any]
    weather: dict[str, Any]
    npk: dict[str, Any]
    recommended_crops: list[str]
    top_3_crops: list[dict[str, Any]]
    selected_crop: str
    profit_per_acre: float
    total_profit: float
    market_data: list[dict[str, Any]]
    cultivation_plan: dict[str, Any]
    required_items: list[dict[str, Any]]
    cost_breakdown: dict[str, Any]
    vendors: dict[str, Any]
    online_links: list[dict[str, Any]]
    final_report: dict[str, Any]
    error: str
    awaiting_selection: bool
