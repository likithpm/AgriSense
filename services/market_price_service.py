"""Search the web for current crop market price information."""

from __future__ import annotations

from datetime import date
import logging
import re
from typing import Any
from urllib.parse import quote_plus

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None


logger = logging.getLogger(__name__)
SEARCH_URL = "https://html.duckduckgo.com/html/"
REQUEST_TIMEOUT = 15


def _fallback_price(crop_name: str, message: str) -> dict[str, str]:
    """Return a stable response when web price retrieval is unavailable."""
    return {
        "crop_name": crop_name,
        "current_price": "Unavailable",
        "source": "fallback",
        "date": date.today().isoformat(),
        "error": message,
    }


def _search_web(crop_name: str) -> list[dict[str, str]]:
    """Search the web and return result titles, snippets, and URLs."""
    query = f"{crop_name} current market price India today"
    response = requests.get(
        SEARCH_URL,
        params={"q": query},
        headers={"User-Agent": "AgriSense-AI/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    if BeautifulSoup is not None:
        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, str]] = []
        for result in soup.select(".result"):
            link = result.select_one(".result__a")
            snippet = result.select_one(".result__snippet")
            if link and link.get("href"):
                results.append({
                    "title": link.get_text(" ", strip=True),
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                    "url": str(link["href"]),
                })
        return results

    # Minimal fallback parser keeps this module usable without bs4 installed.
    links = re.findall(
        r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)',
        response.text,
        flags=re.IGNORECASE,
    )
    return [{"title": "", "snippet": "", "url": url} for url in links]


def _extract_price(text: str) -> str | None:
    """Extract a rupee or INR price with its original unit from text."""
    patterns = (
        r"(?:₹|INR\s*)\s*([0-9][0-9,]*(?:\.\d+)?)\s*(/\s*(?:kg|quintal|qtl|ton|tonne))?",
        r"([0-9][0-9,]*(?:\.\d+)?)\s*(?:rupees?|Rs\.?|INR)\s*(/\s*(?:kg|quintal|qtl|ton|tonne))?",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = match.group(1).replace(",", "")
            unit = (match.group(2) or "").replace(" ", "")
            return f"₹{amount}{unit}"
    return None


def _infer_trend(text: str) -> str:
    """Infer a simple trend label from web text."""
    lowered = text.lower()
    if any(word in lowered for word in ("increasing", " 상승", "rise", "up", "higher")):
        return "increasing"
    if any(word in lowered for word in ("decreasing", "fall", "down", "lower")):
        return "decreasing"
    return "stable"


def get_current_crop_price(crop_name: str) -> dict[str, str]:
    """Search the web and return a current crop price with source and date."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        return _fallback_price(str(crop_name), "Crop name must be a non-empty string")

    crop_name = crop_name.strip()
    try:
        logger.info("Searching web for current price of %s", crop_name)
        results = _search_web(crop_name)
        for result in results:
            text = f"{result['title']} {result['snippet']}"
            price = _extract_price(text)
            if price:
                logger.info("Found web price for %s", crop_name)
                return {
                    "crop_name": crop_name,
                    "current_price": price,
                    "source": result["url"],
                    "date": date.today().isoformat(),
                }
        return _fallback_price(crop_name, "No current price found in web results")
    except (requests.RequestException, ValueError, TypeError, re.error) as exc:
        logger.warning("Web price lookup failed for %s: %s", crop_name, exc)
        return _fallback_price(crop_name, "Unable to retrieve current crop price")


def get_crop_price_trend(crop_name: str) -> dict[str, str]:
    """Search current web reports and return an inferred price trend."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        return {"crop_name": str(crop_name), "trend": "stable", "confidence": "low"}

    crop_name = crop_name.strip()
    try:
        results = _search_web(f"{crop_name} price trend")
        text = " ".join(f"{item['title']} {item['snippet']}" for item in results)
        if not text:
            return {"crop_name": crop_name, "trend": "stable", "confidence": "low"}
        trend = _infer_trend(text)
        confidence = "medium" if len(results) >= 2 else "low"
        return {"crop_name": crop_name, "trend": trend, "confidence": confidence}
    except (requests.RequestException, ValueError, TypeError, re.error) as exc:
        logger.warning("Web trend lookup failed for %s: %s", crop_name, exc)
        return {"crop_name": crop_name, "trend": "stable", "confidence": "low"}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    crop = "muskmelon"
    print(get_current_crop_price(crop))
    print(get_crop_price_trend(crop))
