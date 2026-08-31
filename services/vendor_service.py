"""Discover local and online agricultural vendors for a selected crop."""

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import quote_plus

import requests
import urllib3

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


logger = logging.getLogger(__name__)
REQUEST_TIMEOUT = 5
GOOGLE_PLACES_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/"
WEB_SEARCH_URL = "https://html.duckduckgo.com/html/"
LOCAL_SEARCHES = (
    "{crop} seeds near {location}",
    "fertilizer shops near {location}",
    "agriculture supplier near {location}",
    "farm input dealer near {location}",
)
ONLINE_SEARCHES = (
    "{crop} seeds buy online",
    "{crop} fertilizer online",
    "{crop} irrigation kit online",
)


def _empty_vendors() -> list[dict[str, Any]]:
    """Return an empty vendor collection for failed searches."""
    return []


def _search_web(query: str) -> list[dict[str, str]]:
    """Fetch and parse DuckDuckGo result links for a vendor query."""
    request = {
        "url": WEB_SEARCH_URL,
        "params": {"q": query},
        "headers": {"User-Agent": "AgriSense-AI/1.0"},
        "timeout": REQUEST_TIMEOUT,
    }
    try:
        response = requests.get(**request)
    except requests.exceptions.SSLError:
        logger.warning("Web search unavailable due to SSL verification failure")
        response = requests.get(**request, verify=False)
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

    links = re.findall(
        r'<a[^>]+class=["\'][^"\']*result__a[^"\']*["\'][^>]+href=["\']([^"\']+)',
        response.text,
        flags=re.IGNORECASE,
    )
    return [{"title": "", "snippet": "", "url": url} for url in links]


def _google_places_vendors(query: str) -> list[dict[str, Any]]:
    """Query Google Places Text Search when a Google Maps API key is configured."""
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return []
    response = requests.get(
        GOOGLE_PLACES_URL,
        params={"query": query, "key": api_key},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") not in {"OK", "ZERO_RESULTS"}:
        raise ValueError(f"Google Places returned {payload.get('status', 'unknown status')}")

    vendors: list[dict[str, Any]] = []
    for place in payload.get("results", []):
        vendors.append({
            "name": place.get("name", "Unknown vendor"),
            "address": place.get("formatted_address", ""),
            "rating": place.get("rating"),
            "phone": "",
            "source": "google_maps",
        })
    return vendors


def search_local_vendors(crop_name: str, location_name: str) -> list[dict[str, Any]]:
    """Find nearby agricultural stores using Google Places or Maps search URLs."""
    if not isinstance(crop_name, str) or not isinstance(location_name, str):
        logger.warning("Invalid crop or location for local vendor search")
        return _empty_vendors()
    crop = crop_name.strip()
    location = location_name.strip()
    if not crop or not location:
        logger.warning("Empty crop or location for local vendor search")
        return _empty_vendors()

    logger.info("Local vendor search started for %s in %s", crop, location)
    vendors: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for template in LOCAL_SEARCHES:
            query = template.format(crop=crop, location=location)
            places = _google_places_vendors(query)
            if places:
                for vendor in places:
                    key = vendor["name"].casefold()
                    if key not in seen:
                        vendors.append(vendor)
                        seen.add(key)
            else:
                vendors.append({
                    "name": query,
                    "address": f"Search nearby vendors in {location}",
                    "rating": None,
                    "phone": "",
                    "source": "google_maps",
                    "search_url": GOOGLE_MAPS_SEARCH_URL + quote_plus(query),
                })
        logger.info("Local vendor search completed for %s: %d options", crop, len(vendors))
        return vendors
    except requests.exceptions.SSLError:
        logger.warning("Web search unavailable due to SSL verification failure")
        logger.info("Vendor search fallback activated")
        return _empty_vendors()
    except Exception as exc:
        logger.warning("Local vendor search failed: %s", exc)
        logger.info("Vendor search fallback activated")
        return _empty_vendors()


def search_online_vendors(crop_name: str) -> list[dict[str, Any]]:
    """Find online seed, fertilizer, and agricultural suppliers through web search."""
    if not isinstance(crop_name, str) or not crop_name.strip():
        logger.warning("Invalid crop for online vendor search")
        return _empty_vendors()
    crop = crop_name.strip()
    queries = tuple(query.format(crop=crop) for query in ONLINE_SEARCHES)
    logger.info("Web vendor search started for %s", crop)
    vendors: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for query in queries:
            try:
                search_results = _search_web(query)
            except requests.exceptions.SSLError:
                logger.warning("Web search unavailable due to SSL verification failure")
                search_results = []
            for result in search_results:
                url = result.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                vendors.append({
                    "vendor_name": result.get("title", "Online agricultural supplier"),
                    "website": url,
                    "product": f"{crop} farm inputs",
                    "source": "web",
                })
        logger.info("Web vendor search completed for %s: %d options", crop, len(vendors))
        return vendors
    except requests.exceptions.SSLError:
        logger.warning("Web search unavailable due to SSL verification failure")
        logger.info("Vendor search fallback activated")
        return _empty_vendors()
    except Exception as exc:
        logger.warning("Web vendor search failed: %s", exc)
        logger.info("Vendor search fallback activated")
        return _empty_vendors()


def generate_procurement_plan(crop_name: str, location_name: str) -> dict[str, Any]:
    """Combine local and online procurement options for a crop and location."""
    return {
        "crop_name": crop_name,
        "local_vendors": search_local_vendors(crop_name, location_name),
        "online_vendors": search_online_vendors(crop_name),
    }


def get_vendor_recommendations(crop_name: str, location_name: str) -> dict[str, Any]:
    """Return local and online vendor recommendations without raising errors."""
    try:
        return generate_procurement_plan(crop_name, location_name)
    except Exception as exc:
        logger.exception("Vendor recommendation failed: %s", exc)
        logger.info("Vendor search fallback activated")
        return {"crop_name": crop_name, "local_vendors": [], "online_vendors": []}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(get_vendor_recommendations("Tomato", "Coimbatore"))
