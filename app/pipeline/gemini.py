"""Thin wrapper around google-genai with retries for rate limits and transient errors."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from google import genai
from google.genai import errors, types
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings

log = logging.getLogger(__name__)
RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}


class GeminiUnavailable(RuntimeError):
    """Raised when Gemini keeps failing after retries."""


@lru_cache
def client() -> genai.Client:
    settings = get_settings()
    settings.require_gemini()
    return genai.Client(api_key=settings.gemini_api_key)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, errors.APIError):
        return getattr(exc, "code", None) in RETRYABLE_CODES
    return isinstance(exc, (TimeoutError, ConnectionError))


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential_jitter(initial=2, max=60),
    stop=stop_after_attempt(5),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _call(model: str, contents: str, config: types.GenerateContentConfig) -> types.GenerateContentResponse:
    return client().models.generate_content(model=model, contents=contents, config=config)


def generate(
    prompt: str,
    *,
    system: str | None = None,
    json_schema: dict[str, Any] | None = None,
    google_search: bool = False,
    temperature: float = 0.7,
) -> types.GenerateContentResponse:
    """Run one generation. json_schema enables structured JSON output (not combined with search)."""
    config = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    if json_schema is not None:
        config.response_mime_type = "application/json"
        config.response_json_schema = json_schema
    if google_search:
        config.tools = [types.Tool(google_search=types.GoogleSearch())]
    try:
        return _call(get_settings().gemini_model, prompt, config)
    except errors.APIError as exc:
        raise GeminiUnavailable(f"Gemini error {getattr(exc, 'code', '?')}: {exc}") from exc


def response_text(resp: types.GenerateContentResponse) -> str:
    try:
        return resp.text or ""
    except (ValueError, AttributeError):
        return ""
