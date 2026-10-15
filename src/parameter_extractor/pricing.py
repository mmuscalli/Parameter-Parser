"""
Estimated API cost in USD from token counts.

The API reports tokens used, not money, so the cost is computed here from
Anthropic's published list prices (https://platform.claude.com/docs/en/about-claude/pricing,
checked 2026-10-15). It's an estimate: discounts, regional-inference
multipliers and price changes after that date aren't reflected. A model not
in the table gets no estimate rather than a guess.
"""
from __future__ import annotations
from typing import Optional

PRICES_CHECKED = "2026-10-15"

# model id prefix -> list of (max prompt tokens or None, input $/MTok, output $/MTok); each request
# is priced on its own, by its prompt length
PRICES = {
    "claude-fable-5-1": [(None, 10.0, 50.0)],
    "claude-opus-5-5": [(None, 4.0, 20.0)],
    "claude-opus-5": [(None, 5.0, 25.0)],
    "claude-sonnet-5-5": [(None, 2.0, 10.0)],
    "claude-sonnet-5": [(None, 2.0, 10.0)],
    "claude-haiku-5-5": [(100_000, 0.10, 0.50), (None, 0.50, 2.50)],
}


def _tiers(model: str):
    # longest prefix first, so "claude-opus-5-5" isn't priced as "claude-opus-5"
    for prefix in sorted(PRICES, key=len, reverse=True):
        if model == prefix or model.startswith(prefix + "-"):
            return PRICES[prefix]
    return None


def request_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    """Estimated USD for one request, or None for a model without a known price."""
    tiers = _tiers(model)
    if tiers is None:
        return None
    for limit, in_price, out_price in tiers:
        if limit is None or input_tokens <= limit:
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return None


def format_usd(cost: Optional[float]) -> str:
    if cost is None:
        return "—"
    return f"${cost:.2f}" if cost >= 0.10 else f"${cost:.3f}"
