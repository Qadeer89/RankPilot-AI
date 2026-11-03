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

# Change-category matrix (CW-003, custom-website-write addendum §6): every
# operation belongs to a category, and tier-1 auto-execution can be opted
# into per category rather than only as one all-or-nothing site-wide flag.
# Categories not yet implemented as operations (JSON-LD, canonical, robots,
# redirects, ...) are intentionally absent here -- add them only once a
# real operation exists for them, so this table never promises an opt-in
# for something the execution engine can't actually do yet.
OPERATION_CATEGORY: dict[str, str] = {
    "set_title": "metadata",
    "set_meta_description": "metadata",
}


def change_category_for_operation(operation: str) -> str:
    return OPERATION_CATEGORY.get(operation, "uncategorized")


def is_risk_tier_blocked(risk_tier: int) -> bool:
    return risk_tier >= BLOCKED_RISK_TIER


def requires_approval(website: Website, risk_tier: int, operation: str | None = None) -> bool:
    """`operation` is optional for backward compatibility with any other
    caller that only has a risk tier to go on; passing it lets a tier-1
    change opt into auto-execution per category instead of only via the
    one blanket `auto_execute_risk_tier_1` flag.
    """
    if risk_tier <= 0:
        return False
    if risk_tier == 1:
        if operation is not None:
            category = change_category_for_operation(operation)
            auto_execute_categories = website.automation_policy.get("auto_execute_categories", {})
            if auto_execute_categories.get(category) is True:
                return False
        return not bool(website.automation_policy.get("auto_execute_risk_tier_1", False))
    return True
