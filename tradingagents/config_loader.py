"""Unified configuration loader — reads config.toml and provides typed access.

All tunable parameters live in ``config.toml`` at the project root.
This module loads that file, merges with sensible defaults, and exposes
helper methods to produce the dicts expected by the existing subsystems
(``TradingAgentsGraph``, ``create_broker``, ``pre_screen``, ``resolve_trade``).

Usage::

    from tradingagents.config_loader import load_config

    cfg = load_config()                     # reads ./config.toml
    cfg = load_config("custom/path.toml")   # or a custom path

    # For the pipeline
    graph = TradingAgentsGraph(config=cfg.pipeline_config)

    # For the broker
    broker = create_broker(cfg.broker_config)

    # For the screener
    results = pre_screen(cfg.universe, top_n=cfg.screener_candidates, ...)

Verify your config::

    python -m tradingagents.config_loader
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")


# ── Defaults (used when keys are missing from TOML) ─────────────────────

_DEFAULTS: dict[str, Any] = {
    "llm": {
        "provider": "ollama",
        "deep_think_model": "qwen3:32b",
        "quick_think_model": "qwen3:14b",
        "backend_url": "",
        "quick_backend_url": "",
        "deep_backend_url": "",
        "google_thinking_level": "",
        "openai_reasoning_effort": "",
        "anthropic_effort": "",
    },
    "market": {
        "benchmark_ticker": "^NSEI",
        "benchmark_name": "NIFTY 50",
        "context": "",
        "news_queries": [],
    },
    "data_vendors": {
        "core_stock_apis": "yfinance",
        "technical_indicators": "yfinance",
        "fundamental_data": "yfinance",
        "news_data": "india_rss,yfinance",
        "tool_overrides": {},
    },
    "universe": {
        "tickers": [],  # Empty = use NIFTY_50 from pre_screener
    },
    "screener": {
        "enabled": True,
        "buy_bias": True,
        "candidates": 5,
        "weights": {
            "volume": 25,
            "momentum_5d": 20,
            "momentum_1d": 15,
            "news": 25,
            "extreme": 15,
        },
        "sentiment": {
            "bullish_keywords": [],
            "bearish_keywords": [],
        },
    },
    "portfolio": {
        "max_positions": 10,
        "initial_capital": 10_00_000.0,
    },
    "trading": {
        "mode": "paper",
        "paper_db_path": "data/paper_portfolio.db",
        "sizing": {
            "buy": 0.05,
            "overweight": 0.03,
            "underweight": 0.50,
            "sell": 1.00,
        },
        "guardrails": {
            "max_position_pct": 0.10,
            "min_trade_value": 500.0,
            "max_trade_value": 100_000.0,
        },
    },
    "pipeline": {
        "max_debate_rounds": 1,
        "max_risk_discuss_rounds": 1,
        "max_recur_limit": 100,
        "checkpoint_enabled": False,
        "output_language": "English",
    },
    "paths": {
        "results_dir": "",
        "data_cache_dir": "",
        "memory_log_path": "",
        "memory_log_max_entries": 0,
    },
    "angel_one": {
        "api_key": "",
        "client_id": "",
        "password": "",
        "totp_secret": "",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base* (override wins)."""
    merged = base.copy()
    for key, val in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def _get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dicts."""
    current = data
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k, default)
        if current is default:
            return default
    return current


@dataclass
class TradingConfig:
    """Typed, unified configuration loaded from config.toml.

    Provides convenience properties that produce the exact dict shapes
    expected by existing subsystems — no existing API needs to change.
    """

    _raw: dict = field(repr=False)
    source_path: str = ""

    # ── LLM ──────────────────────────────────────────────────────────

    @property
    def llm_provider(self) -> str:
        return self._raw["llm"]["provider"]

    @property
    def deep_think_model(self) -> str:
        return self._raw["llm"]["deep_think_model"]

    @property
    def quick_think_model(self) -> str:
        return self._raw["llm"]["quick_think_model"]

    @property
    def backend_url(self) -> Optional[str]:
        v = self._raw["llm"]["backend_url"]
        return v if v else None

    @property
    def quick_backend_url(self) -> Optional[str]:
        """Per-model URL for quick thinker; falls back to backend_url."""
        v = self._raw["llm"]["quick_backend_url"]
        return v if v else self.backend_url

    @property
    def deep_backend_url(self) -> Optional[str]:
        """Per-model URL for deep thinker; falls back to backend_url."""
        v = self._raw["llm"]["deep_backend_url"]
        return v if v else self.backend_url

    # ── Market ───────────────────────────────────────────────────────

    @property
    def benchmark_ticker(self) -> str:
        return self._raw["market"]["benchmark_ticker"]

    @property
    def benchmark_name(self) -> str:
        return self._raw["market"]["benchmark_name"]

    @property
    def market_context(self) -> str:
        return self._raw["market"]["context"].strip()

    @property
    def news_queries(self) -> list[str]:
        q = self._raw["market"]["news_queries"]
        return q if q else None

    # ── Universe ─────────────────────────────────────────────────────

    @property
    def universe(self) -> list[str]:
        tickers = self._raw["universe"]["tickers"]
        if tickers:
            return tickers
        # Fall back to NIFTY_50 from pre_screener
        from tradingagents.trading.pre_screener import NIFTY_50
        return NIFTY_50

    # ── Screener ─────────────────────────────────────────────────────

    @property
    def screener_enabled(self) -> bool:
        return self._raw["screener"]["enabled"]

    @property
    def screener_buy_bias(self) -> bool:
        return self._raw["screener"]["buy_bias"]

    @property
    def screener_candidates(self) -> int:
        return self._raw["screener"]["candidates"]

    @property
    def screener_weights(self) -> dict[str, int]:
        return dict(self._raw["screener"]["weights"])

    @property
    def bullish_keywords(self) -> list[str]:
        kw = self._raw["screener"]["sentiment"]["bullish_keywords"]
        return kw if kw else None  # None = use built-in defaults

    @property
    def bearish_keywords(self) -> list[str]:
        kw = self._raw["screener"]["sentiment"]["bearish_keywords"]
        return kw if kw else None

    # ── Portfolio ────────────────────────────────────────────────────

    @property
    def max_positions(self) -> int:
        return self._raw["portfolio"]["max_positions"]

    @property
    def initial_capital(self) -> float:
        return self._raw["portfolio"]["initial_capital"]

    # ── Trading ──────────────────────────────────────────────────────

    @property
    def trading_mode(self) -> str:
        return self._raw["trading"]["mode"]

    @property
    def paper_db_path(self) -> str:
        return self._raw["trading"]["paper_db_path"]

    @property
    def sizing(self) -> dict[str, float]:
        raw = self._raw["trading"]["sizing"]
        return {
            "Buy": raw["buy"],
            "Overweight": raw["overweight"],
            "Underweight": raw["underweight"],
            "Sell": raw["sell"],
            "Hold": 0.0,
        }

    @property
    def guardrails(self) -> dict[str, float]:
        return dict(self._raw["trading"]["guardrails"])

    # ── Pipeline ─────────────────────────────────────────────────────

    @property
    def max_debate_rounds(self) -> int:
        return self._raw["pipeline"]["max_debate_rounds"]

    @property
    def checkpoint_enabled(self) -> bool:
        return self._raw["pipeline"]["checkpoint_enabled"]

    @property
    def output_language(self) -> str:
        return self._raw["pipeline"]["output_language"]

    # ── Paths ────────────────────────────────────────────────────────

    @property
    def results_dir(self) -> str:
        v = self._raw["paths"]["results_dir"]
        return v if v else os.path.join(_TRADINGAGENTS_HOME, "logs")

    @property
    def memory_log_path(self) -> str:
        v = self._raw["paths"]["memory_log_path"]
        return v if v else os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")

    # ── Bridge methods (produce dicts for existing subsystems) ───────

    @property
    def pipeline_config(self) -> dict:
        """Dict compatible with ``TradingAgentsGraph(config=...)``."""
        paths = self._raw["paths"]
        pipeline = self._raw["pipeline"]
        dv = self._raw["data_vendors"]

        return {
            "project_dir": os.path.abspath(
                os.path.join(os.path.dirname(__file__), ".")
            ),
            "results_dir": self.results_dir,
            "data_cache_dir": (
                paths["data_cache_dir"]
                if paths["data_cache_dir"]
                else os.path.join(_TRADINGAGENTS_HOME, "cache")
            ),
            "memory_log_path": self.memory_log_path,
            "memory_log_max_entries": (
                paths["memory_log_max_entries"]
                if paths["memory_log_max_entries"]
                else None
            ),
            # LLM
            "llm_provider": self.llm_provider,
            "deep_think_llm": self.deep_think_model,
            "quick_think_llm": self.quick_think_model,
            "backend_url": self.backend_url,
            "quick_backend_url": self.quick_backend_url,
            "deep_backend_url": self.deep_backend_url,
            "google_thinking_level": (
                self._raw["llm"]["google_thinking_level"] or None
            ),
            "openai_reasoning_effort": (
                self._raw["llm"]["openai_reasoning_effort"] or None
            ),
            "anthropic_effort": (
                self._raw["llm"]["anthropic_effort"] or None
            ),
            # Pipeline
            "max_debate_rounds": pipeline["max_debate_rounds"],
            "max_risk_discuss_rounds": pipeline["max_risk_discuss_rounds"],
            "max_recur_limit": pipeline["max_recur_limit"],
            "checkpoint_enabled": pipeline["checkpoint_enabled"],
            "output_language": pipeline["output_language"],
            # Market
            "benchmark_ticker": self.benchmark_ticker,
            "benchmark_name": self.benchmark_name,
            "market_context": self.market_context,
            "global_news_queries": self.news_queries,
            # Data
            "data_vendors": {
                "core_stock_apis": dv["core_stock_apis"],
                "technical_indicators": dv["technical_indicators"],
                "fundamental_data": dv["fundamental_data"],
                "news_data": dv["news_data"],
            },
            "tool_vendors": dv.get("tool_overrides", {}),
        }

    @property
    def broker_config(self) -> dict:
        """Dict compatible with ``create_broker(config=...)``."""
        cfg = {
            "trading_mode": self.trading_mode,
            "initial_capital": self.initial_capital,
            "paper_db_path": self.paper_db_path,
        }
        # Angel One creds (from TOML or .env fallback)
        angel = self._raw.get("angel_one", {})
        for key in ("api_key", "client_id", "password", "totp_secret"):
            val = angel.get(key, "")
            env_key = f"ANGEL_{key.upper()}"
            cfg[f"angel_{key}"] = val if val else os.environ.get(env_key, "")
        return cfg


def load_config(path: str | Path = "config.toml") -> TradingConfig:
    """Load configuration from a TOML file.

    Args:
        path: Path to the TOML file. Defaults to ``config.toml`` in CWD.

    Returns:
        A :class:`TradingConfig` with all values merged over defaults.
        If the file doesn't exist, returns pure defaults.
    """
    path = Path(path)

    if path.exists():
        logger.info("Loading config from %s", path)
        with open(path, "rb") as f:
            user_config = tomllib.load(f)
    else:
        logger.info("No config file at %s — using defaults", path)
        user_config = {}

    merged = _deep_merge(_DEFAULTS, user_config)
    return TradingConfig(_raw=merged, source_path=str(path))


# ── CLI: verify config ──────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.toml"
    cfg = load_config(config_path)

    print(f"\n📋 TradingAgents Config — loaded from: {cfg.source_path}\n")
    print(f"  LLM provider:      {cfg.llm_provider}")
    print(f"  Deep think model:  {cfg.deep_think_model}")
    print(f"  Quick think model: {cfg.quick_think_model}")
    print(f"  Backend URL:       {cfg.backend_url or '(auto-detect)'}")
    print()
    print(f"  Benchmark:         {cfg.benchmark_name} ({cfg.benchmark_ticker})")
    print(f"  Universe:          {len(cfg.universe)} tickers")
    print(f"  Market context:    {cfg.market_context[:60]}...")
    print()
    print(f"  Screener enabled:  {cfg.screener_enabled}")
    print(f"  Screener mode:     {'buy-biased' if cfg.screener_buy_bias else 'direction-agnostic'}")
    print(f"  Candidates:        {cfg.screener_candidates}")
    print(f"  Screener weights:  {cfg.screener_weights}")
    print()
    print(f"  Trading mode:      {cfg.trading_mode}")
    print(f"  Initial capital:   ₹{cfg.initial_capital:,.0f}")
    print(f"  Max positions:     {cfg.max_positions}")
    print(f"  Position sizing:   {cfg.sizing}")
    print(f"  Guardrails:        {cfg.guardrails}")
    print()
    print(f"  Debate rounds:     {cfg.max_debate_rounds}")
    print(f"  Checkpoint:        {cfg.checkpoint_enabled}")
    print(f"  Output language:   {cfg.output_language}")
    print()

    # Validate
    errors = []
    w = cfg.screener_weights
    total = sum(w.values())
    if total != 100:
        errors.append(f"Screener weights sum to {total}, expected 100")
    if cfg.initial_capital <= 0:
        errors.append("Initial capital must be positive")
    if cfg.max_positions < 1:
        errors.append("Max positions must be at least 1")
    if cfg.screener_candidates < 1:
        errors.append("Screener candidates must be at least 1")

    if errors:
        print("⚠️  Validation warnings:")
        for e in errors:
            print(f"   - {e}")
    else:
        print("✅ Config looks good!")
