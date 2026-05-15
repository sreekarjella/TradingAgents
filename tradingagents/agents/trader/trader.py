"""Trader: turns the Research Manager's investment plan into a concrete transaction proposal."""

from __future__ import annotations

import functools
import logging

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import build_instrument_context
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)

logger = logging.getLogger(__name__)

# Reputable trading desks reject trades whose potential reward is less
# than this multiple of the potential loss. Set as a soft floor: trades
# below this trigger a warning in the audit log so the PM/risk debate
# can review during reflection.
MIN_ACCEPTABLE_RR = 1.5


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = build_instrument_context(company_name)
        investment_plan = state["investment_plan"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a trading agent analyzing market data to make investment decisions. "
                    "Based on your analysis, provide a specific recommendation to buy, sell, or hold. "
                    "Anchor your reasoning in the analysts' reports and the research plan. "
                    "Discipline checklist for actionable trades (Buy/Sell): you MUST specify "
                    "entry_price, stop_loss, take_profit, and risk_reward_ratio. "
                    "Compute risk_reward_ratio honestly as |take_profit - entry_price| / "
                    "|entry_price - stop_loss|. If the resulting R:R is below 1.5, either tighten "
                    "the stop, raise the target, or downgrade to Hold \u2014 do not propose poor "
                    "risk-reward trades."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an investment "
                    f"plan tailored for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this plan as a foundation for evaluating your next "
                    f"trading decision.\n\nProposed Investment Plan: {investment_plan}\n\n"
                    f"Leverage these insights to make an informed and strategic decision."
                ),
            },
        ]

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        _audit_risk_reward(company_name, trader_plan)

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")


def _audit_risk_reward(ticker: str, rendered_plan: str) -> None:
    """Inspect the trader's rendered plan and warn on poor risk-reward.

    Pulled into a helper so the trader_node stays a thin orchestrator and
    so the guardrail can be unit-tested without spinning up an LLM.

    The check is informational \u2014 it does NOT mutate the plan. The
    warning lands in the same audit log the daily_runner already tails,
    so a human (or a future memory-reflection agent) can revisit poorly
    sized trades. Hard-rejecting would silently drop signals; we prefer
    visibility.
    """
    import re

    action = _extract_field(rendered_plan, r"\*\*Action\*\*:\s*(\w+)")
    if not action or action.lower() == "hold":
        return

    entry = _extract_float(rendered_plan, r"\*\*Entry Price\*\*:\s*([\d.]+)")
    stop = _extract_float(rendered_plan, r"\*\*Stop Loss\*\*:\s*([\d.]+)")
    target = _extract_float(rendered_plan, r"\*\*Take Profit\*\*:\s*([\d.]+)")
    declared_rr = _extract_float(rendered_plan, r"\*\*Risk:Reward\*\*:\s*([\d.]+)")

    missing = [k for k, v in {"entry": entry, "stop": stop, "target": target}.items() if v is None]
    if missing:
        logger.warning(
            "\u26a0\ufe0f  R:R guardrail [%s]: %s action missing required fields: %s",
            ticker, action, ", ".join(missing),
        )
        return

    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk == 0:
        logger.warning("\u26a0\ufe0f  R:R guardrail [%s]: stop equals entry, cannot size risk", ticker)
        return
    computed_rr = reward / risk

    if declared_rr is not None and abs(declared_rr - computed_rr) > 0.1:
        logger.warning(
            "\u26a0\ufe0f  R:R guardrail [%s]: declared R:R %.2f disagrees with computed %.2f",
            ticker, declared_rr, computed_rr,
        )

    if computed_rr < MIN_ACCEPTABLE_RR:
        logger.warning(
            "\u26a0\ufe0f  R:R guardrail [%s]: %s @ %.2f, stop %.2f (-%.1f%%), target %.2f (+%.1f%%) "
            "\u2192 R:R %.2f BELOW desk floor of %.1f. Consider tighter stop, higher target, or Hold.",
            ticker, action, entry, stop,
            abs(entry - stop) / entry * 100,
            target,
            abs(target - entry) / entry * 100,
            computed_rr, MIN_ACCEPTABLE_RR,
        )
    else:
        logger.info(
            "\u2705 R:R guardrail [%s]: %s @ %.2f, stop %.2f, target %.2f \u2192 R:R %.2f (\u2265 %.1f)",
            ticker, action, entry, stop, target, computed_rr, MIN_ACCEPTABLE_RR,
        )


def _extract_field(text: str, pattern: str):
    import re
    m = re.search(pattern, text)
    return m.group(1) if m else None


def _extract_float(text: str, pattern: str):
    raw = _extract_field(text, pattern)
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None
