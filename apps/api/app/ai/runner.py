"""Shared plumbing for every AI agent call: budget enforcement, the
AgentRun audit/cost ledger, and uniform failure handling
(RP-0607, AI_AGENT_SPECIFICATION.md #7). Each agent module only supplies
its own prompts, schema, and a `parse_fn` that validates the model's
response into a typed result.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

from openai import APITimeoutError, OpenAIError, RateLimitError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.budget import enforce_daily_budget
from app.ai.client import AINotConfigured, get_openai_client
from app.ai.pricing import estimate_cost_usd
from app.config import get_settings
from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.models.website import Website

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PromptTooLarge(RuntimeError):
    pass


# Everything an AI call can fail with that a caller should degrade on
# (rather than 500): provider/transport errors, a missing key, an
# oversized prompt, and a response that does not match the schema.
AI_CALL_FAILURES = (
    OpenAIError,
    AINotConfigured,
    PromptTooLarge,
    ValidationError,
    ValueError,
    KeyError,
    AttributeError,
)


def classify_ai_failure(exc: BaseException) -> tuple[str, str]:
    """(status, user-facing message) for a failed AI call. `status` is one
    of "unavailable", "invalid_response" or "input_too_large"."""
    if isinstance(exc, AINotConfigured):
        return "unavailable", "AI is not configured on this server, so no AI ideas were added."
    if isinstance(exc, PromptTooLarge):
        return "input_too_large", "There was too much source content for a single AI call, so no AI ideas were added."
    if isinstance(exc, APITimeoutError):
        return "unavailable", "The AI provider timed out, so no AI ideas were added. Try again in a few minutes."
    if isinstance(exc, RateLimitError):
        return "unavailable", "The AI provider is rate limiting requests, so no AI ideas were added. Try again shortly."
    if isinstance(exc, OpenAIError):
        return "unavailable", "The AI provider returned an error, so no AI ideas were added. Try again later."
    return "invalid_response", "The AI returned a response RankPilot could not use, so no AI ideas were added."


def run_ai_agent(
    db: Session,
    website: Website,
    agent_type: AgentType,
    result_reference: uuid.UUID | None,
    *,
    system_prompt: str,
    user_prompt: str,
    response_json_schema: dict,
    parse_fn: Callable[[str], T],
    image_urls: list[str] | None = None,
) -> T:
    settings = get_settings()

    # RP13-014: reject an oversized prompt before spending any budget or
    # tokens on it. user_prompt is built from crawled page content and
    # other untrusted input, which is otherwise unbounded in size.
    if len(user_prompt) > settings.ai_max_prompt_characters:
        raise PromptTooLarge(
            f"Prompt is {len(user_prompt)} characters, over the "
            f"{settings.ai_max_prompt_characters}-character limit (RANKPILOT_AI_MAX_PROMPT_CHARACTERS)."
        )

    # A project without an entitlement gets no paid AI work (no-op unless billing enforcement is on).
    from app.billing.entitlement import check as check_entitlement

    check_entitlement(db, website, "ai")
    enforce_daily_budget(db, website)

    client = get_openai_client()

    agent_run = AgentRun(
        website_id=website.id,
        agent_type=agent_type,
        model=settings.openai_model,
        status=AgentRunStatus.pending,
        started_at=datetime.now(timezone.utc),
        result_reference=result_reference,
    )
    db.add(agent_run)
    db.flush()

    if image_urls:
        # Multi-part content (RankPilot AI Phase 3 "Image Alt Text
        # Automation": "use actual image content where visual analysis
        # is available"). Each image is given as a public URL the model
        # fetches itself -- RankPilot never downloads or re-encodes it,
        # and never claims the model actually saw an image this call
        # didn't attach (see content_agent.py's vision-path prompt).
        user_content = [{"type": "text", "text": user_prompt}] + [
            {"type": "image_url", "image_url": {"url": url}} for url in image_urls
        ]
    else:
        user_content = user_prompt

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_schema", "json_schema": response_json_schema},
            max_tokens=settings.openai_max_output_tokens,
        )

        raw_content = response.choices[0].message.content
        usage = response.usage

        result = parse_fn(raw_content)

        agent_run.input_tokens = usage.prompt_tokens if usage else 0
        agent_run.output_tokens = usage.completion_tokens if usage else 0
        agent_run.estimated_cost = estimate_cost_usd(
            settings.openai_model, agent_run.input_tokens, agent_run.output_tokens
        )
        agent_run.status = AgentRunStatus.succeeded
        agent_run.completed_at = datetime.now(timezone.utc)
        db.flush()
        return result
    except (ValidationError, ValueError, KeyError, AttributeError) as exc:
        logger.warning("AI agent (%s) response failed validation: %s", agent_type.value, exc)
        agent_run.status = AgentRunStatus.failed
        agent_run.completed_at = datetime.now(timezone.utc)
        db.flush()
        raise
    except Exception:
        logger.exception("AI agent (%s) call failed for website %s", agent_type.value, website.id)
        agent_run.status = AgentRunStatus.failed
        agent_run.completed_at = datetime.now(timezone.utc)
        db.flush()
        raise
