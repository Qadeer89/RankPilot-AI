"""Strict structured-output contract for AI proposals (RP-0602,
API_SPECIFICATION.md #4). Every AI response is validated against this
schema before it can touch the database or be shown to a user; nothing
the model returns is trusted implicitly (SECURITY_SPECIFICATION.md #5).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

ALLOWED_OPERATIONS = {"set_title", "set_meta_description"}


class EvidenceRef(BaseModel):
    page_url: str
    finding_code: str


class ProposedAction(BaseModel):
    operation: str = Field(description="One of: " + ", ".join(sorted(ALLOWED_OPERATIONS)))
    target_url: str
    value: str


class OpportunityProposal(BaseModel):
    opportunity_id: str
    summary: str
    evidence: list[EvidenceRef]
    proposed_actions: list[ProposedAction]
    risk_tier: int = Field(ge=0, le=3)
    confidence: float = Field(ge=0.0, le=1.0)
    requires_approval: bool
    validation_plan: list[str]

    def validate_allowed_operations(self) -> None:
        """Raise if the model proposed an operation outside the allowlist.

        Schema validation alone can't express "only these string values
        are allowed actions" as strongly as this explicit check
        (SECURITY_SPECIFICATION.md #5: "Validate AI output against strict
        schemas and allowlisted operations").
        """
        for action in self.proposed_actions:
            if action.operation not in ALLOWED_OPERATIONS:
                raise ValueError(f"Operation '{action.operation}' is not in the allowlist.")


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
