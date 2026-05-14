"""Read and parse TradingAgents pipeline log files.

Scans ``~/.tradingagents/logs/<TICKER>/TradingAgentsStrategy_logs/``
for ``full_states_log_<date>.json`` files and exposes them as structured
``RunSummary`` and ``RunDetail`` objects.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

_LOGS_ROOT = Path.home() / ".tradingagents" / "logs"
_LOG_FILENAME_RE = re.compile(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$")

# Rating keywords → badge colour class (Tailwind)
_RATING_COLOURS = {
    "buy": "bg-green-600",
    "strong buy": "bg-green-700",
    "overweight": "bg-green-600",
    "hold": "bg-yellow-500 text-gray-900",
    "neutral": "bg-yellow-500 text-gray-900",
    "sell": "bg-red-600",
    "strong sell": "bg-red-700",
    "underweight": "bg-red-600",
}


def _extract_rating(decision: str) -> str:
    """Pull the rating keyword from a final_trade_decision blob."""
    if not decision:
        return "N/A"
    lower = decision.lower()
    for keyword in ("strong buy", "strong sell", "overweight", "underweight",
                    "buy", "sell", "hold", "neutral"):
        if keyword in lower:
            return keyword.title()
    return "N/A"


def _rating_colour(rating: str) -> str:
    return _RATING_COLOURS.get(rating.lower(), "bg-gray-500")


# ── Public data classes ──────────────────────────────────────────────────


@dataclass
class RunSummary:
    """Lightweight summary for the sidebar list."""
    ticker: str
    trade_date: str  # yyyy-mm-dd
    rating: str
    rating_colour: str
    file_path: str   # absolute path to JSON

    @property
    def run_id(self) -> str:
        """Unique slug: TICKER__DATE."""
        return f"{self.ticker}__{self.trade_date}"


@dataclass
class PipelineStep:
    """One step in the pipeline flow."""
    key: str          # machine key
    label: str        # human label for the tab
    icon: str         # emoji
    content: str      # raw markdown content


@dataclass
class RunDetail:
    """Full parsed run with every pipeline step."""
    ticker: str
    trade_date: str
    rating: str
    rating_colour: str
    steps: list[PipelineStep] = field(default_factory=list)


# ── Step definitions (order = pipeline flow) ─────────────────────────────

_STEP_DEFS: list[tuple[str, str, str]] = [
    # (state_key / nested path, human label, emoji)
    ("market_report",                      "Market Analysis",     "📈"),
    ("news_report",                        "News Analysis",       "📰"),
    ("sentiment_report",                   "Sentiment Analysis",  "💬"),
    ("fundamentals_report",                "Fundamentals",        "📊"),
    ("investment_debate_state.bull_history","Bull Researcher",     "🐂"),
    ("investment_debate_state.bear_history","Bear Researcher",     "🐻"),
    ("investment_plan",                    "Investment Plan",      "📋"),
    ("trader_investment_decision",         "Trader Decision",      "💹"),
    ("risk_debate_state.aggressive_history",  "Aggressive Analyst",  "🔥"),
    ("risk_debate_state.conservative_history","Conservative Analyst","🛡️"),
    ("risk_debate_state.neutral_history",     "Neutral Analyst",     "⚖️"),
    ("final_trade_decision",               "Final Decision",       "✅"),
]


def _resolve_key(state: dict, dotted_key: str) -> str:
    """Resolve a dotted key like 'investment_debate_state.bull_history'."""
    parts = dotted_key.split(".")
    obj = state
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part, "")
        else:
            return ""
    return obj if isinstance(obj, str) else ""


# ── Public API ───────────────────────────────────────────────────────────


def list_runs(
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    ticker: Optional[str] = None,
) -> list[RunSummary]:
    """Return all available runs, optionally filtered by date range / ticker.

    Results are sorted newest-first, then alphabetically by ticker.
    """
    runs: list[RunSummary] = []

    if not _LOGS_ROOT.exists():
        return runs

    for ticker_dir in sorted(_LOGS_ROOT.iterdir()):
        if not ticker_dir.is_dir():
            continue
        if ticker and ticker_dir.name != ticker:
            continue

        logs_dir = ticker_dir / "TradingAgentsStrategy_logs"
        if not logs_dir.is_dir():
            continue

        for log_file in sorted(logs_dir.iterdir(), reverse=True):
            m = _LOG_FILENAME_RE.search(log_file.name)
            if not m:
                continue

            log_date = date.fromisoformat(m.group(1))
            if from_date and log_date < from_date:
                continue
            if to_date and log_date > to_date:
                continue

            # Quick-parse just the final decision for the rating badge
            try:
                raw = json.loads(log_file.read_text(encoding="utf-8"))
                rating = _extract_rating(raw.get("final_trade_decision", ""))
            except (json.JSONDecodeError, OSError):
                rating = "N/A"

            runs.append(RunSummary(
                ticker=ticker_dir.name,
                trade_date=m.group(1),
                rating=rating,
                rating_colour=_rating_colour(rating),
                file_path=str(log_file),
            ))

    # Sort: newest date first, then ticker alpha
    runs.sort(key=lambda r: (r.trade_date, r.ticker), reverse=True)
    return runs


def get_run_detail(run_id: str) -> Optional[RunDetail]:
    """Load full detail for a run identified by 'TICKER__DATE' slug."""
    parts = run_id.split("__", 1)
    if len(parts) != 2:
        return None

    ticker, trade_date = parts
    log_file = (
        _LOGS_ROOT / ticker / "TradingAgentsStrategy_logs"
        / f"full_states_log_{trade_date}.json"
    )
    if not log_file.exists():
        return None

    try:
        state = json.loads(log_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    rating = _extract_rating(state.get("final_trade_decision", ""))

    steps: list[PipelineStep] = []
    for state_key, label, icon in _STEP_DEFS:
        content = _resolve_key(state, state_key)
        if content:
            steps.append(PipelineStep(
                key=state_key.replace(".", "_"),
                label=label,
                icon=icon,
                content=content,
            ))

    return RunDetail(
        ticker=ticker,
        trade_date=trade_date,
        rating=rating,
        rating_colour=_rating_colour(rating),
        steps=steps,
    )


def available_tickers() -> list[str]:
    """Return sorted list of tickers that have at least one log file."""
    if not _LOGS_ROOT.exists():
        return []
    tickers = []
    for d in sorted(_LOGS_ROOT.iterdir()):
        if d.is_dir() and (d / "TradingAgentsStrategy_logs").is_dir():
            tickers.append(d.name)
    return tickers
