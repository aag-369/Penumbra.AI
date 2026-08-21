"""Tool definitions exposed to the agents' LLM.

Phase 2. Declarations only -- no implementations.

Each entry is a JSON-Schema tool definition. The ``privacy`` field is not part
of the LLM-facing schema; it is a note to whoever implements the tool about what
that tool is allowed to touch. Tools marked ``ciphertext_only`` must return
ciphertexts, never decrypted values.
"""

from __future__ import annotations

from typing import Any

AGENT_TOOLS: dict[str, dict[str, Any]] = {
    "get_market_data": {
        "description": "Current price, 52-week range and dividend yield for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
        "privacy": "public",
    },
    "get_historical_returns": {
        "description": "Daily return series for a ticker over a lookback window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "minimum": 30, "maximum": 2520},
            },
            "required": ["ticker", "days"],
        },
        "privacy": "public",
    },
    "get_correlation_matrix": {
        "description": "Correlation matrix for a set of tickers, from public price history.",
        "input_schema": {
            "type": "object",
            "properties": {"tickers": {"type": "array", "items": {"type": "string"}}},
            "required": ["tickers"],
        },
        "privacy": "public",
    },
    "get_sector_allocations": {
        "description": "Sector weights of the current portfolio.",
        "input_schema": {"type": "object", "properties": {}},
        "privacy": "ciphertext_only",
    },
    "simulate_scenario": {
        "description": "Stress the portfolio under a named scenario.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scenario": {
                    "type": "string",
                    "enum": ["equity_drawdown_20", "rates_up_200bp", "credit_spread_widening", "usd_shock"],
                }
            },
            "required": ["scenario"],
        },
        "privacy": "ciphertext_only",
    },
    "get_esg_scores": {
        "description": "ESG scores for a set of tickers.",
        "input_schema": {
            "type": "object",
            "properties": {"tickers": {"type": "array", "items": {"type": "string"}}},
            "required": ["tickers"],
        },
        "privacy": "public",
    },
}


def tool_schemas() -> list[dict[str, Any]]:
    """Tool definitions in the shape an LLM API expects, with notes stripped."""
    return [
        {"name": name, "description": spec["description"], "input_schema": spec["input_schema"]}
        for name, spec in AGENT_TOOLS.items()
    ]
