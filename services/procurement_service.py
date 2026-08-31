"""Connect cultivation requirements with local and online vendor options."""

from __future__ import annotations

import logging
from typing import Any

from services.cultivation_service import (
    extract_required_items,
    generate_cultivation_plan,
)
from services.vendor_service import get_vendor_recommendations

logger = logging.getLogger(__name__)


def _scale_quantity_description(item_name: str, farm_area_acres: float = 1.0) -> str:
    """Provide realistic agricultural input quantities scaled to farm area."""
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    name = item_name.lower()
    if "seed" in name:
        if area <= 1.0:
            return f"{round(area * 1.5, 1)} - {round(area * 3.0, 1)} kg (For {area} Acre)"
        return f"{round(area * 2.5, 1)} kg (For {area} Acres)"
    if "fertilizer" in name or "npk" in name or "urea" in name or "dap" in name:
        bags = max(1, round(area * 2.5))
        return f"{bags} Bags (~50kg each) for {area} Acre{'s' if area != 1 else ''}"
    if "manure" in name or "fym" in name or "compost" in name:
        tonnes = max(0.5, round(area * 4.0, 1))
        return f"{tonnes} Tonnes (For {area} Acre{'s' if area != 1 else ''})"
    if "mulch" in name:
        rolls = max(1, round(area * 2))
        return f"{rolls} Rolls (400m x 1.2m) for {area} Acre{'s' if area != 1 else ''}"
    if "irrigation" in name or "drip" in name:
        return f"Drip Lateral Kit for {area} Acre{'s' if area != 1 else ''}"
    if "pesticide" in name or "fungicide" in name:
        litres = max(0.5, round(area * 1.2, 1))
        return f"{litres} L / kg as preventive dosage ({area} Acre{'s' if area != 1 else ''})"
    if "micronutrient" in name:
        return f"{max(1.0, round(area * 2.0, 1))} kg foliar grade for {area} Acre{'s' if area != 1 else ''}"
    return f"As recommended for {area} Acre{'s' if area != 1 else ''}"


def generate_procurement_requirements(
    crop_name: str,
    cultivation_plan: dict[str, Any] | None = None,
    farm_area_acres: float = 1.0,
) -> list[dict[str, str]]:
    """Convert cultivation required items into scaled procurement purchases."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        logger.warning("Invalid crop name for procurement requirements")
        return []

    crop_name = crop_name.strip()
    area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
    try:
        if cultivation_plan and isinstance(cultivation_plan.get("timeline"), list):
            plan = cultivation_plan
        else:
            plan = generate_cultivation_plan(crop_name)
        
        items = extract_required_items(plan)
        logger.info("Required items extracted for %s: %s", crop_name, items)
        requirements: list[dict[str, str]] = []
        for item in items:
            if isinstance(item, dict):
                item_name = str(item.get("item", "")).strip()
                if item_name:
                    qty = _scale_quantity_description(item_name, area)
                    requirements.append({"item": item_name, "quantity": qty})
            elif isinstance(item, str) and item.strip():
                item_name = item.strip()
                qty = _scale_quantity_description(item_name, area)
                requirements.append({"item": item_name, "quantity": qty})
        return requirements
    except Exception:
        logger.exception("Unable to generate procurement requirements for %s", crop_name)
        return []


def generate_vendor_plan(crop_name: str, location_name: str) -> dict[str, list[dict[str, Any]]]:
    """Combine required-item generation with vendor recommendations."""
    empty: dict[str, list[dict[str, Any]]] = {
        "local_vendors": [],
        "online_vendors": [],
    }
    if (
        not isinstance(crop_name, str)
        or not crop_name.strip()
        or not isinstance(location_name, str)
        or not location_name.strip()
    ):
        logger.warning("Invalid crop or location for vendor plan")
        return empty

    try:
        logger.info("Vendor lookup started for %s in %s", crop_name, location_name)
        vendors = get_vendor_recommendations(crop_name.strip(), location_name.strip())
        if not isinstance(vendors, dict):
            return empty
        return {
            "local_vendors": vendors.get("local_vendors", []) or [],
            "online_vendors": vendors.get("online_vendors", []) or [],
        }
    except Exception:
        logger.exception("Vendor lookup failed for %s", crop_name)
        return empty


def create_procurement_plan(
    crop_name: str,
    location_name: str,
    cultivation_plan: dict[str, Any] | None = None,
    farm_area_acres: float = 1.0,
) -> dict[str, Any]:
    """Return required materials and local/online procurement options scaled to farm area."""
    empty: dict[str, Any] = {
        "crop_name": crop_name,
        "required_items": [],
        "local_vendors": [],
        "online_vendors": [],
    }
    if not isinstance(crop_name, str) or not isinstance(location_name, str):
        logger.warning("Invalid input for procurement plan")
        return empty

    crop_name = crop_name.strip()
    location_name = location_name.strip()
    if not crop_name or not location_name:
        logger.warning("Empty input for procurement plan")
        return empty

    try:
        required_items = generate_procurement_requirements(
            crop_name,
            cultivation_plan=cultivation_plan,
            farm_area_acres=farm_area_acres,
        )
        vendors = generate_vendor_plan(crop_name, location_name)
        result = {
            "crop_name": crop_name,
            "required_items": required_items,
            "local_vendors": vendors["local_vendors"],
            "online_vendors": vendors["online_vendors"],
        }
        logger.info("Procurement plan completed for %s", crop_name)
        return result
    except Exception:
        logger.exception("Procurement plan failed for %s", crop_name)
        return empty


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = create_procurement_plan("Tomato", "Coimbatore", farm_area_acres=1.5)
    print(result)
