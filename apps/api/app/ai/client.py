"""Server-side OpenAI client (RP-0601, AI_AGENT_SPECIFICATION.md #3).

The API key lives only in server environment configuration. It is never
passed to the frontend, logged, or included in any response body.
"""

from __future__ import annotations

from openai import OpenAI

from app.config import get_settings


class AINotConfigured(RuntimeError):
    pass


def get_openai_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise AINotConfigured("RANKPILOT_OPENAI_API_KEY is not set.")
    return OpenAI(api_key=settings.openai_api_key, timeout=settings.openai_request_timeout_seconds)
