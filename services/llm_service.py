"""Central Google Gemini LLM service for AgriSense."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
DEFAULT_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
DEFAULT_TIMEOUT = float(os.getenv("GEMINI_TIMEOUT", "10.0"))


def get_gemini_api_key() -> str | None:
    """Retrieve Gemini API key from environment."""
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_llm(
    model: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """Instantiate and return a reusable ChatGoogleGenerativeAI instance."""
    api_key = get_gemini_api_key()
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set in environment")
        return None

    model_name = model or DEFAULT_MODEL
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
            max_retries=1,
        )
    except Exception as exc:
        logger.exception("Failed to initialize ChatGoogleGenerativeAI: %s", exc)
        return None


def extract_text_from_response(content: Any) -> str:
    """Convert string or structured list response content into clean text."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "".join(parts).strip()
    return str(content).strip()


def parse_json_from_response(content: Any) -> Any:
    """Extract and parse JSON from model response text, stripping markdown code blocks if present."""
    text = extract_text_from_response(content)
    
    # Strip markdown fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        # Check if text has leading/trailing braces
        json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if json_match:
            text = json_match.group(1).strip()

    return json.loads(text)


def invoke_llm(prompt: str, model: str | None = None, temperature: float = DEFAULT_TEMPERATURE) -> str:
    """Invoke the Gemini LLM and return the extracted text response."""
    llm = get_llm(model=model, temperature=temperature)
    if llm is None:
        raise RuntimeError("Gemini LLM is not configured or GEMINI_API_KEY is missing")

    response = llm.invoke(prompt)
    return extract_text_from_response(response.content)


def invoke_json_llm(prompt: str, model: str | None = None, temperature: float = DEFAULT_TEMPERATURE) -> Any:
    """Invoke the Gemini LLM and parse the output as JSON."""
    llm = get_llm(model=model, temperature=temperature)
    if llm is None:
        raise RuntimeError("Gemini LLM is not configured or GEMINI_API_KEY is missing")

    response = llm.invoke(prompt)
    return parse_json_from_response(response.content)
