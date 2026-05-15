"""Tests for the trader's R:R discipline guardrail.

The guardrail does not mutate the trade plan; it logs warnings/info that
get picked up by the audit log so a human (or a future memory-reflection
agent) can revisit poorly sized trades. These tests pin the log-message
contract so future refactors keep the audit signal alive.
"""

from __future__ import annotations

import logging

import pytest

from tradingagents.agents.trader.trader import _audit_risk_reward, MIN_ACCEPTABLE_RR


def _plan(action: str, entry: float | None = None, stop: float | None = None,
          target: float | None = None, declared_rr: float | None = None) -> str:
    """Build a minimal rendered TraderProposal that the guardrail can parse."""
    parts = [f"**Action**: {action}", "", "**Reasoning**: t"]
    if entry is not None:
        parts.append(f"**Entry Price**: {entry}")
    if stop is not None:
        parts.append(f"**Stop Loss**: {stop}")
    if target is not None:
        parts.append(f"**Take Profit**: {target}")
    if declared_rr is not None:
        parts.append(f"**Risk:Reward**: {declared_rr}")
    return "\n\n".join(parts)


# ── Happy path ──────────────────────────────────────────────────────────────

def test_good_rr_logs_info(caplog):
    # entry 100, stop 95 (risk 5), target 115 (reward 15) → R:R = 3.0
    with caplog.at_level(logging.INFO, logger="tradingagents.agents.trader.trader"):
        _audit_risk_reward("RELIANCE.NS", _plan("Buy", 100, 95, 115, 3.0))
    assert any("R:R 3.00" in r.message for r in caplog.records), caplog.text
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_hold_skips_audit(caplog):
    # Hold with no fields should not warn — guardrail only audits actionable trades.
    with caplog.at_level(logging.WARNING, logger="tradingagents.agents.trader.trader"):
        _audit_risk_reward("RELIANCE.NS", _plan("Hold"))
    assert caplog.records == []


# ── Sad paths the guardrail must catch ─────────────────────────────────────

def test_bad_rr_logs_warning(caplog):
    # The exact ADANIENT shape from our cold-start audit:
    # entry 2712.9, stop 2152.03 (risk 560.87), target 2950 (reward 237.1)
    # → R:R = 0.42 (terrible!)
    with caplog.at_level(logging.WARNING, logger="tradingagents.agents.trader.trader"):
        _audit_risk_reward("ADANIENT.NS", _plan("Buy", 2712.9, 2152.03, 2950))
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns, "Expected an R:R warning for sub-floor trade"
    assert "BELOW desk floor" in warns[0].message


def test_missing_required_fields_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="tradingagents.agents.trader.trader"):
        _audit_risk_reward("X.NS", _plan("Buy", entry=100, target=110))  # no stop
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns and "missing required fields" in warns[0].message
    assert "stop" in warns[0].message


def test_zero_risk_warns(caplog):
    # Stop at the same price as entry would mean zero-risk; guardrail must
    # not divide by zero.
    with caplog.at_level(logging.WARNING, logger="tradingagents.agents.trader.trader"):
        _audit_risk_reward("X.NS", _plan("Buy", 100, 100, 110))
    warns = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warns and "stop equals entry" in warns[0].message


def test_declared_rr_disagreement_flagged(caplog):
    # Computed R:R is 3.0; agent claimed 1.5 — flag the inconsistency so
    # we catch hallucinated numbers.
    with caplog.at_level(logging.WARNING, logger="tradingagents.agents.trader.trader"):
        _audit_risk_reward("X.NS", _plan("Buy", 100, 95, 115, declared_rr=1.5))
    warns = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("disagrees with computed" in w for w in warns)


def test_floor_value_is_one_point_five():
    # Sanity: the constant matches the desk policy documented in the
    # PortfolioManager prompt so prompt and code stay in sync.
    assert MIN_ACCEPTABLE_RR == 1.5
