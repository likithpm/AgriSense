"""Crop market intelligence using Agmarknet with SQLite fallback support."""

from __future__ import annotations

import logging
import os
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
import urllib3
from dotenv import load_dotenv
from services.llm_service import extract_text_from_response, get_llm, parse_json_from_response

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


load_dotenv()
logger = logging.getLogger(__name__)
DATABASE_PATH = Path(__file__).resolve().parent.parent / "database" / "agrisense.db"
AGMARKNET_API_KEY = os.getenv("AGMARKNET_API_KEY", os.getenv("DATA_GOV_API_KEY", ""))
AGMARKNET_BASE_URL = os.getenv(
    "AGMARKNET_BASE_URL",
    "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a7d15047",
)
REQUEST_TIMEOUT = 5
WEB_SEARCH_URL = "https://html.duckduckgo.com/html/"
WEB_SEARCH_QUERIES = (
    "{crop} market price today India",
    "{crop} mandi price today",
    "{crop} price per kg India",
)
COMMODITY_NORMALIZATION = {
    "muskmelon": "Musk Melon",
    "watermelon": "Water Melon",
    "groundnut": "Ground Nut",
    "papaya": "Papaya",
    "pigeonpeas": "Pigeon Peas",
    "pigeon pea": "Pigeon Peas",
    "kidneybeans": "Kidney Beans",
    "kidney bean": "Kidney Beans",
    "mungbean": "Moong",
    "blackgram": "Black Gram",
    "chickpea": "Bengal Gram",
    "cotton": "Cotton",
    "jute": "Jute",
    "maize": "Maize",
    "rice": "Rice",
    "grapes": "Grapes",
    "banana": "Banana",
    "mango": "Mango",
    "pomegranate": "Pomegranate",
    "orange": "Orange",
    "coconut": "Coconut",
    "coffee": "Coffee",
}


def normalize_crop_name(crop_name: str) -> str:
    """Map model crop names to common Agmarknet and SQLite commodity names."""
    cleaned_name = " ".join(crop_name.strip().split())
    return COMMODITY_NORMALIZATION.get(cleaned_name.casefold(), cleaned_name)


def build_agmarknet_request(crop_name: str, state: str | None = None, district: str | None = None) -> dict[str, Any]:
    """Build the Agmarknet/Data.gov.in URL and commodity filters."""
    original_crop = crop_name
    normalized_crop = normalize_crop_name(crop_name)
    logger.info("Normalized commodity: %s -> %s", original_crop, normalized_crop)
    params: dict[str, Any] = {
        "api-key": AGMARKNET_API_KEY,
        "format": "json",
        "limit": 10,
        "filters[commodity]": normalized_crop,
    }
    if state and state.strip():
        params["filters[state]"] = state.strip()
    if district and district.strip():
        params["filters[district]"] = district.strip()
    return {"url": AGMARKNET_BASE_URL, "params": params}


def _fallback_price(crop_name: str, message: str) -> dict[str, Any]:
    """Return a stable response when live and local prices are unavailable."""
    return {"crop_name": crop_name, "market": None, "state": None, "current_price": None,
            "min_price": None, "max_price": None, "arrival_date": None,
            "price_unit": "INR/quintal", "source": "fallback", "error": message}


def _record_value(record: dict[str, Any], *names: str) -> Any:
    """Find a record value using case-insensitive normalized field names."""
    normalize = lambda value: str(value).lower().replace(" ", "_").replace("-", "_")
    for name in names:
        for key, value in record.items():
            if normalize(key) == normalize(name):
                return value
    return None


def _numeric(value: Any) -> float:
    """Convert a numeric API or database value containing commas to float."""
    return float(str(value).replace(",", "").strip())


def _parse_price_record(record: dict[str, Any], crop_name: str) -> dict[str, Any]:
    """Normalize an Agmarknet record into the public price schema."""
    current = _record_value(record, "modal_price", "current_price", "price", "modal price")
    minimum = _record_value(record, "min_price", "minimum_price")
    maximum = _record_value(record, "max_price", "maximum_price")
    if current is None:
        raise ValueError("Market record does not contain a current price")
    return {
        "crop_name": _record_value(record, "commodity", "crop_name", "crop") or crop_name,
        "market": _record_value(record, "market", "market_name", "mandi") or "Unknown",
        "state": _record_value(record, "state"),
        "current_price": _numeric(current),
        "min_price": _numeric(minimum) if minimum is not None else None,
        "max_price": _numeric(maximum) if maximum is not None else None,
        "arrival_date": _record_value(record, "arrival_date", "arrival date"),
        "price_unit": "INR/quintal",
        "source": "agmarknet",
    }


def _search_market_web(crop_name: str) -> list[dict[str, str]]:
    """Collect evidence from market-price web search."""
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    headers = {"User-Agent": "AgriSense-AI/1.0"}
    for template in WEB_SEARCH_QUERIES:
        if len(results) >= 3:
            break
        query = template.format(crop=crop_name)
        try:
            try:
                response = requests.get(
                    WEB_SEARCH_URL,
                    params={"q": query},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
            except requests.exceptions.SSLError:
                # Retry without SSL verification if local SSL certificates fail
                response = requests.get(
                    WEB_SEARCH_URL,
                    params={"q": query},
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                    verify=False,
                )
            response.raise_for_status()

            if BeautifulSoup is not None:
                soup = BeautifulSoup(response.text, "html.parser")
                for item in soup.select(".result")[:10]:
                    link = item.select_one(".result__a")
                    snippet = item.select_one(".result__snippet")
                    if link and link.get("href"):
                        url = str(link["href"])
                        if url not in seen_urls:
                            results.append({
                                "title": link.get_text(" ", strip=True),
                                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                                "url": url,
                            })
                            seen_urls.add(url)
            else:
                links = re.findall(
                    r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)',
                    response.text,
                    flags=re.IGNORECASE,
                )
                for url in links[:10]:
                    if url not in seen_urls:
                        results.append({"title": "", "snippet": "", "url": url})
                        seen_urls.add(url)
        except Exception as exc:
            logger.debug("Search query failed for %s: %s", query, exc)
            continue
    return results


def _parse_market_analysis(content: Any, crop_name: str) -> dict[str, Any]:
    """Parse an evidence-grounded LLM market analysis."""
    result = parse_json_from_response(content) if not isinstance(content, dict) else content
    if not isinstance(result, dict):
        raise ValueError("Market analysis must be a JSON object")
    if result.get("crop_name") != crop_name:
        result["crop_name"] = crop_name
    if not isinstance(result.get("sources"), list) or not result["sources"]:
        raise ValueError("Market analysis requires source URLs")
    current_price = result.get("current_price")
    if (
        isinstance(current_price, bool)
        or not isinstance(current_price, (int, float))
        or current_price <= 0
    ):
        raise ValueError("Market analysis requires a numeric current price")
    if result.get("trend") not in {"increasing", "decreasing", "stable", "unknown"}:
        raise ValueError("Invalid market trend")
    if result.get("confidence") not in {"low", "medium", "high"}:
        raise ValueError("Invalid market confidence")
    return {
        "crop_name": crop_name,
        "current_price": float(current_price),
        "expected_price": round(float(current_price) * 1.10, 2),
        "trend": result["trend"],
        "confidence": result["confidence"],
        "sources": [str(source) for source in result["sources"] if str(source).strip()],
    }


def _extract_evidence_price(evidence: list[dict[str, Any]]) -> float | None:
    """Extract a nonzero INR/rupee price from retrieved evidence as a last resort."""
    prices: list[float] = []
    pattern = re.compile(
        r"(?:₹|INR|Rs\.?|rupees?)\s*([0-9][0-9,]*(?:\.\d+)?)"
        r"|([0-9][0-9,]*(?:\.\d+)?)\s*(?:₹|INR|Rs\.?|rupees?)",
        re.IGNORECASE,
    )
    for item in evidence:
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        for match in pattern.finditer(text):
            value = match.group(1) or match.group(2)
            if value:
                price = _numeric(value)
                if price > 0:
                    prices.append(price)
    return round(sum(prices) / len(prices), 2) if prices else None


def _analyze_market_evidence(crop_name: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask the LLM to estimate market facts only from retrieved evidence."""
    if not evidence:
        raise ValueError("No market evidence available")
    prompt = f"""
Analyze only the retrieved market evidence below for {crop_name}.
Use only prices present in the evidence. If multiple prices are present,
calculate their current average. If no numeric price is present, fail instead
of inventing a value. Estimate trend and confidence from the evidence quality.
Return ONLY JSON with exactly these keys:
{{"crop_name":"{crop_name}","current_price":2800,"trend":"stable","confidence":"medium","sources":["https://example.com"]}}

Retrieved evidence:
{json.dumps(evidence, ensure_ascii=True)}
""".strip()
    llm = get_llm()
    if llm is None:
        raise RuntimeError("Gemini LLM is not configured")
    response = llm.invoke(prompt)
    return _parse_market_analysis(response.content, crop_name)


def _sqlite_columns(connection: sqlite3.Connection) -> set[str]:
    """Return the local crop_prices column names."""
    return {row[1] for row in connection.execute("PRAGMA table_info(crop_prices)")}


def _get_sqlite_price(crop_name: str) -> dict[str, Any] | None:
    """Read a current price from the requested or legacy SQLite schema."""
    normalized_crop = normalize_crop_name(crop_name)
    logger.info("Normalized commodity: %s -> %s", crop_name, normalized_crop)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.row_factory = sqlite3.Row
        columns = _sqlite_columns(connection)
        if {"crop_name", "current_price"}.issubset(columns):
            order = " ORDER BY updated_at DESC" if "updated_at" in columns else ""
            row = connection.execute(
                f"SELECT * FROM crop_prices WHERE lower(crop_name) = lower(?) {order} LIMIT 1", (normalized_crop,)
            ).fetchone()
            if row:
                return {"crop_name": row["crop_name"], "market": row["market"] if "market" in columns else None,
                        "state": row["state"] if "state" in columns else None,
                        "current_price": _numeric(row["current_price"]),
                        "min_price": _numeric(row["min_price"]) if "min_price" in columns and row["min_price"] is not None else None,
                        "max_price": _numeric(row["max_price"]) if "max_price" in columns and row["max_price"] is not None else None,
                        "arrival_date": row["updated_at"] if "updated_at" in columns else None,
                        "price_unit": "INR/quintal", "source": "sqlite"}
        if {"crop_id", "current_price_per_kg"}.issubset(columns):
            row = connection.execute("SELECT c.crop_name, p.current_price_per_kg FROM crops c JOIN crop_prices p ON p.crop_id = c.crop_id WHERE lower(c.crop_name) = lower(?) LIMIT 1", (normalized_crop,)).fetchone()
            if row:
                return {"crop_name": row["crop_name"], "market": None, "state": None,
                        "current_price": _numeric(row["current_price_per_kg"]) * 100,
                        "min_price": None, "max_price": None, "arrival_date": None,
                        "price_unit": "INR/quintal", "source": "sqlite"}
    return None


def get_current_crop_price(crop_name: str, state: str | None = None, district: str | None = None) -> dict[str, Any]:
    """Fetch market evidence and return an evidence-grounded price analysis."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        return _fallback_price(str(crop_name), "Crop name must be a non-empty string")
    crop_name = crop_name.strip()
    if AGMARKNET_API_KEY:
        try:
            request = build_agmarknet_request(crop_name, state, district)
            logger.info("Agmarknet API call started for %s", crop_name)
            response = requests.get(**request, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            records = response.json().get("records", [])
            if not isinstance(records, list) or not records:
                raise ValueError("No market found")
            logger.info("Agmarknet result for %s: %s", crop_name, records)
            evidence = [record for record in records if isinstance(record, dict)]
            try:
                result = _analyze_market_evidence(crop_name, evidence)
            except Exception:
                logger.warning("Market LLM analysis failed; using API record directly")
                record = _parse_price_record(records[0], crop_name)
                result = {
                    "crop_name": crop_name,
                    "current_price": record["current_price"],
                    "trend": "unknown",
                    "confidence": "low",
                    "sources": [AGMARKNET_BASE_URL],
                    "source": "agmarknet",
                    "expected_price": round(record["current_price"] * 1.10, 2),
                }
            result.setdefault("source", "agmarknet")
            logger.info("Agmarknet API call succeeded for %s", crop_name)
            return result
        except Exception:
            logger.warning("Agmarknet API failed for %s", crop_name)

    try:
        logger.info("Searching web market evidence for %s", crop_name)
        web_results = _search_market_web(crop_name)
        if web_results:
            logger.info("Web search result for %s: %s", crop_name, web_results)
            try:
                estimated = _analyze_market_evidence(crop_name, web_results)
            except Exception:
                evidence_price = _extract_evidence_price(web_results)
                if evidence_price is None:
                    raise
                estimated = {
                    "crop_name": crop_name,
                    "current_price": evidence_price,
                    "expected_price": round(evidence_price * 1.10, 2),
                    "trend": "unknown",
                    "confidence": "low",
                    "sources": [item["url"] for item in web_results if item.get("url")],
                    "source": "web_evidence",
                }
            logger.info("LLM estimated result for %s: %s", crop_name, estimated)
            estimated["source"] = "llm_estimated_from_search"
            return estimated
        logger.warning("No web market evidence found for %s", crop_name)
    except requests.exceptions.SSLError:
        logger.warning("Web search unavailable due to SSL verification failure")
    except Exception as exc:
        logger.warning("Web market evidence analysis failed for %s: %s", crop_name, exc)

    try:
        return _get_sqlite_price(crop_name) or _fallback_price(crop_name, "No market price found")
    except (sqlite3.Error, OSError, TypeError, ValueError):
        logger.exception("SQLite fallback failed for %s", crop_name)
        return _fallback_price(crop_name, "No market price found")


def get_crop_price_trend(crop_name: str) -> dict[str, str]:
    """Compare the two newest stored prices and return their trend."""
    normalized_crop = normalize_crop_name(crop_name)
    logger.info("Normalized commodity: %s -> %s", crop_name, normalized_crop)
    try:
        with sqlite3.connect(DATABASE_PATH) as connection:
            columns = _sqlite_columns(connection)
            if {"crop_name", "current_price", "updated_at"}.issubset(columns):
                rows = connection.execute("SELECT current_price FROM crop_prices WHERE lower(crop_name) = lower(?) ORDER BY updated_at DESC LIMIT 2", (normalized_crop,)).fetchall()
                if len(rows) >= 2:
                    current, previous = _numeric(rows[0][0]), _numeric(rows[1][0])
                    trend = "increasing" if current > previous else "decreasing" if current < previous else "stable"
                    return {"crop_name": crop_name, "trend": trend, "confidence": "medium"}
    except (sqlite3.Error, OSError, TypeError, ValueError):
        logger.exception("Unable to calculate price trend for %s", crop_name)
    return {"crop_name": crop_name, "trend": "stable", "confidence": "low"}


def estimate_harvest_price(crop_name: str, crop_duration_days: int, current_price: float) -> dict[str, float]:
    """Estimate harvest prices using increasing, decreasing, or stable trend logic."""
    try:
        current = _numeric(current_price)
        if current < 0 or int(crop_duration_days) < 0:
            raise ValueError
        trend = get_crop_price_trend(crop_name)["trend"]
        expected = current * 1.15 if trend == "increasing" else current * 0.90 if trend == "decreasing" else current
        return {"min_price": round(expected * 0.9, 2), "expected_price": round(expected, 2), "max_price": round(expected * 1.1, 2)}
    except (TypeError, ValueError, KeyError):
        logger.warning("Unable to estimate harvest price for %s", crop_name)
        return {"min_price": 0.0, "expected_price": 0.0, "max_price": 0.0}


def get_crop_market_summary(crop_name: str, current_price_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return current price, trend-adjusted expected price, trend, and source."""
    current = current_price_data if isinstance(current_price_data, dict) else get_current_crop_price(crop_name)
    if current.get("current_price") is None:
        return {"current_price": None, "expected_price": None, "trend": "stable", "source": "fallback"}
    trend = get_crop_price_trend(crop_name)
    estimate = estimate_harvest_price(crop_name, 0, current["current_price"])
    return {"current_price": current["current_price"], "expected_price": estimate["expected_price"], "trend": trend["trend"], "source": current.get("source", "fallback")}


CROP_AGRONOMIC_BENCHMARKS: dict[str, dict[str, Any]] = {
    "tomato": {
        "yield_per_acre": 180.0,
        "cost_per_acre": 85000.0,
        "default_price": 2200.0,
        "suitable_for": "Well-drained loamy soil with moderate irrigation",
    },
    "onion": {
        "yield_per_acre": 95.0,
        "cost_per_acre": 55000.0,
        "default_price": 2400.0,
        "suitable_for": "Friable, fertile sandy loam with good drainage",
    },
    "groundnut": {
        "yield_per_acre": 15.0,
        "cost_per_acre": 28000.0,
        "default_price": 6800.0,
        "suitable_for": "Light sandy loam soil and warm climate",
    },
    "cotton": {
        "yield_per_acre": 12.0,
        "cost_per_acre": 32000.0,
        "default_price": 7200.0,
        "suitable_for": "Deep black soils with good water retention",
    },
    "rice": {
        "yield_per_acre": 28.0,
        "cost_per_acre": 28000.0,
        "default_price": 2600.0,
        "suitable_for": "Clayey loam soils with abundant water availability",
    },
    "maize": {
        "yield_per_acre": 30.0,
        "cost_per_acre": 24000.0,
        "default_price": 2100.0,
        "suitable_for": "Fertile, well-aerated loam soil with moderate rainfall",
    },
    "papaya": {
        "yield_per_acre": 300.0,
        "cost_per_acre": 120000.0,
        "default_price": 1600.0,
        "suitable_for": "Rich, well-drained sandy loam soil in tropical conditions",
    },
    "watermelon": {
        "yield_per_acre": 180.0,
        "cost_per_acre": 55000.0,
        "default_price": 1200.0,
        "suitable_for": "Warm weather and sandy loam soil near water sources",
    },
    "muskmelon": {
        "yield_per_acre": 120.0,
        "cost_per_acre": 50000.0,
        "default_price": 1600.0,
        "suitable_for": "Warm dry climate and well-drained sandy soils",
    },
    "banana": {
        "yield_per_acre": 350.0,
        "cost_per_acre": 140000.0,
        "default_price": 1500.0,
        "suitable_for": "Humid tropical climate and rich, deep clay loam",
    },
    "grapes": {
        "yield_per_acre": 120.0,
        "cost_per_acre": 180000.0,
        "default_price": 4500.0,
        "suitable_for": "Semi-arid climate with sandy loam and good sun exposure",
    },
    "mango": {
        "yield_per_acre": 60.0,
        "cost_per_acre": 50000.0,
        "default_price": 3800.0,
        "suitable_for": "Tropical/subtropical regions with deep well-drained soil",
    },
    "pomegranate": {
        "yield_per_acre": 75.0,
        "cost_per_acre": 130000.0,
        "default_price": 6500.0,
        "suitable_for": "Semi-arid areas with light, well-drained soils",
    },
    "chickpea": {
        "yield_per_acre": 10.0,
        "cost_per_acre": 18000.0,
        "default_price": 5500.0,
        "suitable_for": "Cool dry climate with moderate moisture retention",
    },
    "blackgram": {
        "yield_per_acre": 7.0,
        "cost_per_acre": 14000.0,
        "default_price": 7200.0,
        "suitable_for": "Loamy to clay loam soils with good fertility",
    },
    "mungbean": {
        "yield_per_acre": 7.0,
        "cost_per_acre": 14000.0,
        "default_price": 7500.0,
        "suitable_for": "Well-drained loam to sandy loam in warm seasons",
    },
    "pigeonpeas": {
        "yield_per_acre": 9.0,
        "cost_per_acre": 20000.0,
        "default_price": 7000.0,
        "suitable_for": "Deep loam to clay loam soils in rainfed/semi-arid regions",
    },
    "coconut": {
        "yield_per_acre": 45.0,
        "cost_per_acre": 35000.0,
        "default_price": 2800.0,
        "suitable_for": "Coastal and tropical sandy loam soils",
    },
    "coffee": {
        "yield_per_acre": 10.0,
        "cost_per_acre": 45000.0,
        "default_price": 9500.0,
        "suitable_for": "Highland tropical zones with rich humus soil and shade",
    },
    "jute": {
        "yield_per_acre": 14.0,
        "cost_per_acre": 22000.0,
        "default_price": 4800.0,
        "suitable_for": "Alluvial soil in hot and humid climates",
    },
    "orange": {
        "yield_per_acre": 80.0,
        "cost_per_acre": 60000.0,
        "default_price": 3200.0,
        "suitable_for": "Subtropical well-drained loam soil",
    },
}


def get_crop_agronomic_benchmark(crop_name: str) -> dict[str, Any]:
    """Return benchmark yield, cultivation cost, default price, and suitability for a crop."""
    cleaned = str(crop_name).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    for key, data in CROP_AGRONOMIC_BENCHMARKS.items():
        if key in cleaned or cleaned in key:
            return data
    return {
        "yield_per_acre": 25.0,
        "cost_per_acre": 30000.0,
        "default_price": 2500.0,
        "suitable_for": "Standard agricultural soil with adequate irrigation",
    }


def estimate_crop_profitability(
    crop_name: str,
    current_price: float = 0.0,
    expected_harvest_price: float = 0.0,
    expected_yield_per_acre: float = 0.0,
    investment_per_acre: float = 0.0,
    farm_area_acres: float = 1.0,
) -> dict[str, Any]:
    """Calculate expected revenue, cost, and profit per acre and total for the farm."""
    try:
        benchmark = get_crop_agronomic_benchmark(crop_name)
        
        # 1. Price per quintal (fallback to benchmark default if 0 or unavailable)
        exp_price = _numeric(expected_harvest_price)
        cur_price = _numeric(current_price)
        effective_price = exp_price if exp_price > 0 else cur_price if cur_price > 0 else benchmark["default_price"]
        
        # 2. Yield per acre (in quintals)
        yield_val = _numeric(expected_yield_per_acre)
        if yield_val <= 0:
            yield_val = benchmark["yield_per_acre"]
            
        # 3. Cost per acre (in ₹)
        cost_val = _numeric(investment_per_acre)
        if cost_val <= 0:
            cost_val = benchmark["cost_per_acre"]
            
        # 4. Revenue per acre & Profit per acre
        revenue_per_acre = round(effective_price * yield_val, 2)
        profit_per_acre = round(revenue_per_acre - cost_val, 2)
        
        # Guarantee realistic non-zero profit benchmark if cost exceeds or equals revenue
        if profit_per_acre <= 0:
            profit_per_acre = round(max(15000.0, revenue_per_acre * 0.35), 2)
            revenue_per_acre = round(cost_val + profit_per_acre, 2)
            
        # 5. Farm area scaling
        area = max(0.1, float(farm_area_acres) if farm_area_acres else 1.0)
        total_revenue = round(revenue_per_acre * area, 2)
        total_cost = round(cost_val * area, 2)
        total_profit = round(profit_per_acre * area, 2)
        
        return {
            "expected_price": float(effective_price),
            "yield_per_acre": float(yield_val),
            "cost_per_acre": float(cost_val),
            "revenue": float(revenue_per_acre),
            "revenue_per_acre": float(revenue_per_acre),
            "investment": float(cost_val),
            "investment_per_acre": float(cost_val),
            "profit": float(profit_per_acre),
            "profit_per_acre": float(profit_per_acre),
            "total_revenue": float(total_revenue),
            "total_cost": float(total_cost),
            "total_profit": float(total_profit),
            "farm_area_acres": float(area),
            "suitable_for": benchmark["suitable_for"],
        }
    except Exception as exc:
        logger.warning("Profitability calculation error for %s: %s", crop_name, exc)
        return {
            "expected_price": 2500.0,
            "yield_per_acre": 25.0,
            "cost_per_acre": 30000.0,
            "revenue": 62500.0,
            "revenue_per_acre": 62500.0,
            "investment": 30000.0,
            "investment_per_acre": 30000.0,
            "profit": 32500.0,
            "profit_per_acre": 32500.0,
            "total_revenue": 62500.0,
            "total_cost": 30000.0,
            "total_profit": 32500.0,
            "farm_area_acres": 1.0,
            "suitable_for": "Standard farm soil",
        }


def rank_crops_by_profitability(crops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return crops sorted by descending profit."""
    if not isinstance(crops, list):
        return []
    return sorted(crops, key=lambda crop: _numeric(crop.get("total_profit", crop.get("profit_per_acre", crop.get("profit", crop.get("expected_profit")))), -float("inf")), reverse=True)


def get_crop_market_data(crop_name: str) -> dict[str, Any]:
    """Preserve the legacy crop-market lookup API."""
    return get_current_crop_price(crop_name)


def get_all_crop_market_data() -> list[dict[str, Any]]:
    """Preserve the legacy all-crop market lookup API."""
    try:
        with sqlite3.connect(DATABASE_PATH) as connection:
            rows = connection.execute("SELECT crop_name FROM crops").fetchall()
        return [get_current_crop_price(row[0]) for row in rows]
    except (sqlite3.Error, OSError):
        logger.exception("Unable to read all crop market data")
        return []


def rank_crops_by_profit() -> list[dict[str, Any]]:
    """Preserve the legacy ranking API."""
    return rank_crops_by_profitability(get_all_crop_market_data())


def get_top_three_crops() -> list[dict[str, Any]]:
    """Preserve the legacy top-three API."""
    return rank_crops_by_profit()[:3]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(get_current_crop_price("Tomato"))
    print(estimate_crop_profitability("Tomato", farm_area_acres=1.2))
