"""Collect crop requirements and generate structured cultivation plans."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv
from services.llm_service import extract_text_from_response, get_llm, parse_json_from_response

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


load_dotenv()
logger = logging.getLogger(__name__)
SEARCH_URL = "https://html.duckduckgo.com/html/"
REQUEST_TIMEOUT = 5
DEFAULT_DURATION_DAYS = 120


def _fallback_requirements(crop_name: str) -> dict[str, Any]:
    """Return the minimum requirements structure when web research fails."""
    return {
        "crop_name": crop_name,
        "seeds": [],
        "fertilizers": [],
        "equipment": [],
        "pesticides": [],
        "duration_days": DEFAULT_DURATION_DAYS,
    }


def _search_crop_information(crop_name: str, session: requests.Session) -> str:
    """Search the web and combine useful result text for a crop."""
    query = f"{crop_name} cultivation seed fertilizer irrigation equipment pesticide harvest duration"
    response = session.get(
        SEARCH_URL,
        params={"q": query},
        headers={"User-Agent": "AgriSense-AI/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    if BeautifulSoup is None:
        return re.sub(r"<[^>]+>", " ", response.text)

    soup = BeautifulSoup(response.text, "html.parser")
    snippets = [element.get_text(" ", strip=True) for element in soup.select(".result")]
    text = "\n".join(snippets[:8])
    if not text:
        raise ValueError("No crop information found")
    return text


def _parse_requirements_from_text(crop_name: str, text: str) -> dict[str, Any]:
    """Extract conservative requirement lists and duration from search text."""
    lowered = text.lower()

    def words_after(keywords: tuple[str, ...], limit: int = 4) -> list[str]:
        for keyword in keywords:
            match = re.search(rf"{re.escape(keyword)}[^.:;\n]*[:\-]?\s*([^.;\n]+)", text, re.IGNORECASE)
            if match:
                values = [item.strip(" ,") for item in re.split(r",|\band\b", match.group(1), flags=re.IGNORECASE)]
                return [item for item in values if 2 <= len(item) <= 80][:limit]
        return []

    duration_match = re.search(r"(?:harvest|maturity|duration)[^\d]{0,30}(\d{2,3})\s*days?", lowered)
    duration = int(duration_match.group(1)) if duration_match else DEFAULT_DURATION_DAYS
    return {
        "crop_name": crop_name,
        "seeds": words_after(("seed", "seeds", "planting material")),
        "fertilizers": words_after(("fertilizer", "fertilizers", "manure")),
        "equipment": words_after(("equipment", "machinery", "irrigation")),
        "pesticides": words_after(("pesticide", "pesticides", "insecticide")),
        "duration_days": duration,
    }


def get_crop_requirements(crop_name: str) -> dict[str, Any]:
    """Search the web and return seed, input, equipment, and duration needs."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        return _fallback_requirements(str(crop_name))

    crop_name = crop_name.strip()
    session = requests.Session()
    try:
        logger.info("Searching cultivation requirements for %s", crop_name)
        text = _search_crop_information(crop_name, session)
        requirements = _parse_requirements_from_text(crop_name, text)
        logger.info("Crop requirements retrieved for %s", crop_name)
        return requirements
    except requests.exceptions.SSLError:
        logger.warning("Web search unavailable due to SSL verification failure")
        return _fallback_requirements(crop_name)
    except (requests.RequestException, ValueError, TypeError, re.error) as exc:
        logger.warning("Crop requirements search failed for %s: %s", crop_name, exc)
        return _fallback_requirements(crop_name)
    finally:
        session.close()


def _fallback_timeline(crop_name: str, duration_days: int) -> list[dict[str, Any]]:
    """Return a simple deterministic cultivation timeline."""
    return [
        {"day": 1, "stage": "Land Preparation", "activities": ["Field cleaning", "Deep ploughing"]},
        {"day": 7, "stage": "Seed Sowing", "activities": [f"Sow {crop_name} seeds"]},
        {"day": 15, "stage": "Fertilizer Application", "activities": ["Apply recommended fertilizer"]},
        {"day": max(30, duration_days // 2), "stage": "Crop Maintenance", "activities": ["Monitor irrigation and pests"]},
        {"day": duration_days, "stage": "Harvest", "activities": [f"Harvest {crop_name} crop"]},
    ]


def _parse_plan(content: Any, crop_name: str, duration_days: int) -> dict[str, Any]:
    """Parse and validate the model's JSON cultivation plan."""
    plan = parse_json_from_response(content) if not isinstance(content, dict) else content
    if not isinstance(plan, dict) or not isinstance(plan.get("timeline"), list):
        raise ValueError("Invalid cultivation plan")

    timeline: list[dict[str, Any]] = []
    for item in plan["timeline"]:
        if not isinstance(item, dict):
            continue
        try:
            day = int(item.get("day", 1))
        except (TypeError, ValueError):
            continue
        activities = item.get("activities", [])
        if day < 1 or not isinstance(activities, list):
            continue
        timeline.append({
            "day": min(day, duration_days),
            "stage": str(item.get("stage", "Cultivation")),
            "activities": [str(activity) for activity in activities if str(activity).strip()],
        })
    if not timeline:
        raise ValueError("Cultivation plan has no valid timeline entries")
    return {"crop_name": crop_name, "timeline": sorted(timeline, key=lambda item: item["day"])}


def generate_cultivation_plan(crop_name: str) -> dict[str, Any]:
    """Generate a JSON cultivation timeline using crop requirements and the LLM."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        return {"crop_name": str(crop_name), "timeline": []}

    crop_name = crop_name.strip()
    requirements = get_crop_requirements(crop_name)
    duration_days = int(requirements.get("duration_days", DEFAULT_DURATION_DAYS))
    prompt = f"""
Create a realistic cultivation timeline for {crop_name} over {duration_days} days.
Use these researched requirements:
{json.dumps(requirements, sort_keys=True)}

Return ONLY valid JSON in this format:
{{"crop_name": "{crop_name}", "timeline": [{{"day": 1, "stage": "Land Preparation", "activities": ["Field cleaning"]}}]}}
Include clear stages, day numbers, and practical activity lists.
""".strip()
    try:
        logger.info("Generating cultivation plan for %s with Gemini", crop_name)
        llm = get_llm()
        if llm is None:
            raise RuntimeError("Gemini LLM is not configured")
        response = llm.invoke(prompt)
        return _parse_plan(response.content, crop_name, duration_days)
    except Exception:
        logger.exception("Cultivation plan generation failed; using fallback timeline")
        return {"crop_name": crop_name, "timeline": _fallback_timeline(crop_name, duration_days)}


def extract_required_items(cultivation_plan: dict[str, Any]) -> list[dict[str, str]]:
    """Return unique purchasable agricultural inputs and their quantities.

    Requirements may be supplied as top-level lists or embedded in timeline
    activities. Unspecified quantities remain ``As recommended`` rather than
    being invented.
    """
    if not isinstance(cultivation_plan, dict):
        return []
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    def quantity_from(text: str) -> str:
        match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(kg|g|litres?|liters?|l|bags?|units?)\b",
            text,
            re.IGNORECASE,
        )
        return f"{match.group(1)} {match.group(2)}" if match else "As recommended"

    def add(item: Any, quantity: Any = None) -> None:
        if not isinstance(item, str):
            return
        cleaned = item.strip(" ,.-")
        if not cleaned:
            return
        key = cleaned.casefold()
        if key in seen:
            return
        items.append({
            "item": cleaned,
            "quantity": str(quantity).strip() if quantity else quantity_from(cleaned),
        })
        seen.add(key)

    crop_name = str(cultivation_plan.get("crop_name", "Crop")).strip().title()
    category_names = {
        "seeds": f"{crop_name} Seeds",
        "fertilizers": "NPK Fertilizer",
        "fertilizer": "NPK Fertilizer",
        "manure": "Organic Manure",
        "pesticides": "Recommended Pesticide",
        "pesticide": "Recommended Pesticide",
        "fungicides": "Recommended Fungicide",
        "fungicide": "Recommended Fungicide",
        "irrigation": "Irrigation Equipment",
        "irrigation_equipment": "Irrigation Equipment",
        "equipment": "Farm Equipment",
        "mulch": "Mulch",
        "micronutrients": "Micronutrients",
        "micronutrient": "Micronutrients",
    }

    for key in (
        "seeds", "fertilizers", "fertilizer", "manure", "pesticides",
        "pesticide", "fungicides", "fungicide", "irrigation",
        "irrigation_equipment", "equipment", "mulch", "micronutrients",
        "micronutrient", "required_items",
    ):
        values = cultivation_plan.get(key, [])
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            for value in values:
                if isinstance(value, dict):
                    add(value.get("item"), value.get("quantity"))
                elif key == "required_items":
                    add(str(value))
                else:
                    text = str(value).strip()
                    add(text if text else category_names[key])

    timeline = cultivation_plan.get("timeline", [])
    if isinstance(timeline, list):
        for stage in timeline:
            if not isinstance(stage, dict):
                continue
            activity_text = " ".join(
                [str(stage.get("stage", ""))]
                + [str(activity) for activity in stage.get("activities", [])]
            )
            lowered = activity_text.casefold()
            quantity = quantity_from(activity_text)
            if "seed" in lowered:
                add(f"{crop_name} Seeds", quantity)
            if "fertilizer" in lowered:
                add("NPK Fertilizer", quantity)
            if "manure" in lowered or "compost" in lowered:
                add("Organic Manure", quantity)
            if "pesticide" in lowered or "insecticide" in lowered:
                add("Recommended Pesticide", quantity)
            if "fungicide" in lowered:
                add("Recommended Fungicide", quantity)
            if "irrigation" in lowered or "drip" in lowered:
                add("Irrigation Equipment", quantity)
            if "mulch" in lowered:
                add("Mulch", quantity)
            if "micronutrient" in lowered or "micro nutrient" in lowered:
                add("Micronutrients", quantity)

    logger.info("Extracted required items: %s", items)
    return items


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    plan = generate_cultivation_plan("muskmelon")
    print(plan)
    print("Required items:", extract_required_items({**get_crop_requirements("muskmelon"), **plan}))
