"""Risk-tier and automation-policy gating (RP-0701,
SEO_AUTOMATION_ENGINE.md #4).

Tier 0: analysis only, never reaches here.
Tier 1: narrow, reversible changes — auto-executable only if the website's
automation_policy explicitly opts in; otherwise needs approval like any
other tier.
Tier 2: material changes — approval required, no opt-out.
Tier 3: blocked outright for MVP; there is no "explicit override" UI yet,
and SEO_AUTOMATION_ENGINE.md #4 allows blocking tier 3 by default.
"""

from __future__ import annotations

from app.models.website import Website

BLOCKED_RISK_TIER = 3


def is_risk_tier_blocked(risk_tier: int) -> bool:
    return risk_tier >= BLOCKED_RISK_TIER


def requires_approval(website: Website, risk_tier: int) -> bool:
    if risk_tier <= 0:
        return False
    if risk_tier == 1:
        return not bool(website.automation_policy.get("auto_execute_risk_tier_1", False))
    return True
