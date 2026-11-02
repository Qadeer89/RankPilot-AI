"""Per-model USD cost per 1K tokens, used only to estimate and log spend
(RP-0607). Approximate; check current OpenAI pricing before relying on
this for billing-grade accuracy.
"""

from __future__ import annotations

MODEL_PRICING_USD_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # (input, output)
    "gpt-4o-mini": (0.00015, 0.0006),
    "gpt-4o": (0.0025, 0.01),
}

DEFAULT_PRICING = (0.001, 0.003)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = MODEL_PRICING_USD_PER_1K_TOKENS.get(model, DEFAULT_PRICING)
    return round((input_tokens / 1000) * input_price + (output_tokens / 1000) * output_price, 6)
