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

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.ai.budget import enforce_daily_budget
from app.ai.client import get_openai_client
from app.ai.pricing import estimate_cost_usd
from app.config import get_settings
from app.models.agent_run import AgentRun, AgentRunStatus, AgentType
from app.models.website import Website

logger = logging.getLogger(__name__)

T = TypeVar("T")


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
) -> T:
    enforce_daily_budget(db, website.id)

    settings = get_settings()
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

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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
