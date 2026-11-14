"""Strict structured-output contract for AI proposals (RP-0602,
API_SPECIFICATION.md #4). Every AI response is validated against this
schema before it can touch the database or be shown to a user; nothing
the model returns is trusted implicitly (SECURITY_SPECIFICATION.md #5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

ALLOWED_OPERATIONS = {"set_title", "set_meta_description", "set_alt_text", "set_canonical"}

# A canonical change can silently de-index a page or merge it into the
# wrong one if the destination is wrong -- far less forgiving than a
# title/meta-description typo. "Never automatically change canonical
# URLs where the correct destination is uncertain" (Phase 3 spec) is
# enforced here, in code, rather than trusted to the model's own
# risk_tier/requires_approval judgment: every set_canonical action
# forces tier >= 2, which policy.requires_approval() always gates on
# approval with no auto-execute opt-in, regardless of what the model
# itself returned.
MIN_RISK_TIER_BY_OPERATION = {"set_canonical": 2}


class EvidenceRef(BaseModel):
    model_config = {"extra": "forbid"}

    page_url: str
    finding_code: str


class ProposedAction(BaseModel):
    # CW-018 (custom-website-write addendum §5): "The LLM cannot provide
    # connector IDs, permissions, credentials, arbitrary paths or
    # executable commands." OpenAI's own strict JSON schema
    # (RESPONSE_JSON_SCHEMA below, additionalProperties: False) already
    # keeps a real API response from smuggling an extra field like
    # "connector_id" or "file_path" through -- extra="forbid" here makes
    # the same guarantee hold for any other caller that constructs or
    # parses a ProposedAction directly (tests, a future code path), not
    # just the OpenAI structured-output call.
    model_config = {"extra": "forbid"}

    operation: str = Field(description="One of: " + ", ".join(sorted(ALLOWED_OPERATIONS)))
    target_url: str
    value: str


class OpportunityProposal(BaseModel):
    model_config = {"extra": "forbid"}

    opportunity_id: str
    summary: str
    evidence: list[EvidenceRef]
    proposed_actions: list[ProposedAction]
    risk_tier: int = Field(ge=0, le=3)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    validation_plan: list[str]

    def validate_allowed_operations(self) -> None:
        """Raise if the model proposed an operation outside the allowlist,
        or at a risk tier below that operation's enforced floor.

        Schema validation alone can't express "only these string values
        are allowed actions" as strongly as this explicit check
        (SECURITY_SPECIFICATION.md #5: "Validate AI output against strict
        schemas and allowlisted operations").
        """
        for action in self.proposed_actions:
            if action.operation not in ALLOWED_OPERATIONS:
                raise ValueError(f"Operation '{action.operation}' is not in the allowlist.")
            min_tier = MIN_RISK_TIER_BY_OPERATION.get(action.operation)
            if min_tier is not None and self.risk_tier < min_tier:
                raise ValueError(
                    f"Operation '{action.operation}' requires risk_tier >= {min_tier}, "
                    f"got {self.risk_tier}."
                )


RESPONSE_JSON_SCHEMA = {
    "name": "opportunity_proposal",
    "schema": {
        "type": "object",
        "properties": {
            "opportunity_id": {"type": "string"},
            "summary": {"type": "string"},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page_url": {"type": "string"},
                        "finding_code": {"type": "string"},
                    },
                    "required": ["page_url", "finding_code"],
                    "additionalProperties": False,
                },
            },
            "proposed_actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": sorted(ALLOWED_OPERATIONS)},
                        "target_url": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "required": ["operation", "target_url", "value"],
                    "additionalProperties": False,
                },
            },
            "risk_tier": {"type": "integer", "minimum": 0, "maximum": 3},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "requires_approval": {"type": "boolean"},
            "validation_plan": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "opportunity_id",
            "summary",
            "evidence",
            "proposed_actions",
            "risk_tier",
            "confidence",
            "requires_approval",
            "validation_plan",
        ],
        "additionalProperties": False,
    },
    "strict": True,
}
