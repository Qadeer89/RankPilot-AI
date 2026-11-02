"""Post-change deterministic validation (RP-0706,
SEO_AUTOMATION_ENGINE.md #7: "verify ... expected content/metadata is
present").
"""

from __future__ import annotations

from app.connectors.wordpress import WordPressCredentials, current_meta_description, current_title, get_resource


def validate_wordpress_change(
    credentials: WordPressCredentials, post_type: str, post_id: int, operation: str, expected_value: str
) -> tuple[bool, dict]:
    resource = get_resource(credentials, post_type, post_id)

    if operation == "set_title":
        actual_value = current_title(resource)
    elif operation == "set_meta_description":
        actual_value = current_meta_description(resource)
    else:
        raise ValueError(f"Unknown operation: {operation}")

    passed = actual_value == expected_value
    return passed, {"operation": operation, "expected": expected_value, "actual": actual_value}
