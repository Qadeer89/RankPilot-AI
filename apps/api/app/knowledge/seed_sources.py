"""Which repo docs feed the AI Knowledge Assistant's seed corpus, and
under what category. An explicit allowlist rather than "everything in
docs/" -- several docs there are internal planning/gap-analysis
artifacts (implementation requirements, MVP roadmaps, dev task lists)
that are often stale or pre-decision, and would let the assistant
confidently answer from a plan that was later changed. Only docs that
describe the product/system as actually built are included.
"""

from __future__ import annotations

SEED_DOC_CATEGORIES: dict[str, str] = {
    "MASTER_SPEC.md": "general",
    "USER_ONBOARDING.md": "onboarding",
    "AI_AGENT_SPECIFICATION.md": "ai_automation",
    "SEO_AUTOMATION_ENGINE.md": "seo_automation",
    "WEBSITE_CONNECTORS.md": "connectors",
    "CONNECTOR_OPERATIONS_REFERENCE.md": "connectors",
    "SECURITY_SPECIFICATION.md": "security",
    "SYSTEM_ARCHITECTURE.md": "architecture",
    "API_SPECIFICATION.md": "architecture",
    "DATABASE_SCHEMA.md": "architecture",
    "QA_TEST_STRATEGY.md": "qa",
    "DEPLOYMENT_GUIDE.md": "deployment",
    "README.md": "general",
}

# Where an assistant answer in this category should point the user,
# for the chatbot's navigation/action capability (Part 4: "ability to
# navigate/link to relevant app sections").
CATEGORY_DASHBOARD_PATH: dict[str, str] = {
    "onboarding": "/dashboard/onboarding",
    "connectors": "/dashboard/websites",
    "seo_automation": "/dashboard/websites",
    "ai_automation": "/dashboard/websites",
    "security": "/dashboard",
    "architecture": "/dashboard",
    "qa": "/dashboard",
    "deployment": "/dashboard",
    "general": "/dashboard",
    "admin_authored": "/dashboard",
}
