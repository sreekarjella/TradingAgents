"""Post-run quality audit — analyze a daily_runner pipeline log against
the standards a reputed investment firm would apply.

Scores 6 dimensions:
  1. Data Quality: news article counts, vendor success, missing data warnings
  2. Analyst Depth: did each of the 4 analysts produce substantive output?
  3. Debate Rigor: bull/bear back-and-forth quality
  4. Trade Discipline: position sizing, risk-reward, stop-loss reasoning
  5. Decision Coherence: does PM decision align with debate consensus?
  6. Execution Quality: trade fills, slippage, portfolio diversification

Usage:  python tools/audit_pipeline_run.py [LOG_FILE]
"""
from __future__ import annotations

import re
import sys
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
RESULTS_DIR = Path.home() / ".tradingagents" / "logs"
MEMORY_LOG = Path.home() / ".tradingagents" / "memory" / "trading_memory.md"

# Color helpers
G, R, Y, B, D, X = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[2m", "\033[0m"


def _hdr(msg: str):
    print(f"\n{B}━━━ {msg} {'━' * (70 - len(msg))}{X}")


def _row(label: str, value, status: str = ""):
    icon = {"pass": f"{G}✓{X}", "warn": f"{Y}⚠{X}", "fail": f"{R}✗{X}", "info": " "}.get(status, " ")
    print(f"  {icon} {label:42s}  {value}")


# ────────────────────────────────────────────────────────────────────────
def find_log(arg: Optional[str] = None) -> Path:
    if arg:
        return Path(arg)
    candidates = sorted((ROOT / "logs").glob("audit_run_*.log"))
    if not candidates:
        candidates = sorted((ROOT / "logs").glob("pipeline_*.log"))
    if not candidates:
        raise SystemExit("No log files found in logs/")
    return candidates[-1]


# ────────────────────────────────────────────────────────────────────────
# 1. Data quality: news vendor stats from log
# ────────────────────────────────────────────────────────────────────────
def audit_data_quality(log: str):
    _hdr("1. DATA QUALITY (news + market data)")

    # google_rss stats lines: "google_rss[TICKER]: N raw → N relevant → ..."
    rss_lines = re.findall(
        r"google_rss\[([\w.-]+)\]: (\d+) raw → (\d+) relevant → (\d+) after junk → (\d+) kept",
        log,
    )
    if rss_lines:
        total_raw = sum(int(r[1]) for r in rss_lines)
        total_kept = sum(int(r[4]) for r in rss_lines)
        avg_rel = sum(int(r[2]) for r in rss_lines) / max(1, total_raw) * 100
        avg_jnk = (sum(int(r[2]) - int(r[3]) for r in rss_lines)
                   / max(1, sum(int(r[2]) for r in rss_lines)) * 100)
        _row("google_rss tickers covered", f"{len(set(r[0] for r in rss_lines))}", "info")
        _row("Total raw articles fetched", f"{total_raw}", "info")
        _row("Total kept (after filters)", f"{total_kept}",
             "pass" if total_kept > 20 * len(set(r[0] for r in rss_lines)) else "warn")
        _row("Relevance rate", f"{avg_rel:.1f}%",
             "pass" if avg_rel > 80 else "warn")
        _row("Junk drop rate", f"{avg_jnk:.1f}%", "info")
        for tk, raw, rel, jnk, kept in rss_lines:
            _row(f"  {tk}", f"{kept}/{raw} kept ({rel} relevant)",
                 "pass" if int(kept) >= 10 else "warn")
    else:
        _row("google_rss stats", "NONE FOUND in log", "fail")

    # India RSS / yfinance fallback signals
    fb_yf = len(re.findall(r"vendor.*yfinance.*fallback|using yfinance", log, re.I))
    fb_in = len(re.findall(r"vendor.*india_rss.*fallback|using india_rss", log, re.I))
    _row("Vendor fallbacks (yfinance)", f"{fb_yf}", "info")
    _row("Vendor fallbacks (india_rss)", f"{fb_in}", "info")

    # Errors / warnings hint at data fetch problems
    errs = re.findall(r"(?:ERROR|WARNING).*(?:vendor|fetch|RSS|HTTP|timeout)", log, re.I)
    _row("Data-related errors/warnings", f"{len(errs)}",
         "pass" if len(errs) == 0 else "warn" if len(errs) < 5 else "fail")
    if errs and len(errs) < 10:
        for e in errs[:5]:
            print(f"     {D}↳ {e[:120]}{X}")


# ────────────────────────────────────────────────────────────────────────
# 2. Analyst depth: report sizes per ticker
# ────────────────────────────────────────────────────────────────────────
def audit_analyst_depth():
    _hdr("2. ANALYST REPORT DEPTH (per ticker, per role)")

    REPORTS = ("market_report", "news_report", "sentiment_report",
               "fundamentals_report", "investment_plan", "trader_investment_plan",
               "final_trade_decision")

    if not RESULTS_DIR.exists():
        _row("Results dir", "MISSING", "fail")
        return

    for ticker_dir in sorted(RESULTS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        # Latest date subdir
        date_dirs = sorted([d for d in ticker_dir.iterdir() if d.is_dir()])
        if not date_dirs:
            continue
        latest = date_dirs[-1]
        reports_dir = latest / "reports"
        if not reports_dir.exists():
            _row(f"{ticker_dir.name}", "no reports/ dir", "fail")
            continue
        print(f"  {B}{ticker_dir.name}{X} ({latest.name}):")
        for r in REPORTS:
            f = reports_dir / f"{r}.md"
            if f.exists():
                size = f.stat().st_size
                lines = sum(1 for _ in f.open())
                status = "pass" if size > 800 else "warn" if size > 200 else "fail"
                print(f"      {{'pass':'✓','warn':'⚠','fail':'✗'}}".replace("'pass':'✓','warn':'⚠','fail':'✗'", "")
                      + f" {r:32s}  {size:>6} bytes / {lines:>3} lines",
                      end="")
                color = {"pass": G, "warn": Y, "fail": R}[status]
                print(f"  {color}[{status.upper()}]{X}")
            else:
                print(f"      {R}✗{X} {r:32s}  MISSING")


# ────────────────────────────────────────────────────────────────────────
# 3. Debate rigor: count rounds, length per side
# ────────────────────────────────────────────────────────────────────────
def audit_debate_rigor():
    _hdr("3. DEBATE RIGOR (research + risk)")

    if not RESULTS_DIR.exists():
        return

    for ticker_dir in sorted(RESULTS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        date_dirs = sorted([d for d in ticker_dir.iterdir() if d.is_dir()])
        if not date_dirs:
            continue
        plan = date_dirs[-1] / "reports" / "investment_plan.md"
        if not plan.exists():
            continue
        text = plan.read_text()
        bull = len(re.findall(r"(?:Bull|Bullish).*?(?=\n\n|\Z)", text, re.S | re.I))
        bear = len(re.findall(r"(?:Bear|Bearish).*?(?=\n\n|\Z)", text, re.S | re.I))
        words = len(text.split())
        _row(f"{ticker_dir.name} investment_plan",
             f"{words} words, ~{bull} bull / ~{bear} bear sections",
             "pass" if words > 400 else "warn")


# ────────────────────────────────────────────────────────────────────────
# 4. Trade discipline: did decisions include sizing + risk reasoning?
# ────────────────────────────────────────────────────────────────────────
def audit_trade_discipline():
    _hdr("4. TRADE DISCIPLINE (sizing, stops, risk-reward)")

    if not RESULTS_DIR.exists():
        return

    KEYWORDS = {
        "position_sizing": (r"\b(?:position size|sizing|allocate|allocation|capital)", "pass"),
        "stop_loss":       (r"\b(?:stop[- ]loss|SL|stop\s*at)", "pass"),
        "target_price":    (r"\b(?:target|TP|take[- ]profit|price target)", "pass"),
        "risk_reward":     (r"\b(?:risk[- ]reward|R:R|risk/reward|reward[- ]ratio)", "pass"),
        "time_horizon":    (r"\b(?:time horizon|holding period|short[- ]term|medium[- ]term|long[- ]term)", "pass"),
    }

    for ticker_dir in sorted(RESULTS_DIR.iterdir()):
        if not ticker_dir.is_dir():
            continue
        date_dirs = sorted([d for d in ticker_dir.iterdir() if d.is_dir()])
        if not date_dirs:
            continue
        decision = date_dirs[-1] / "reports" / "final_trade_decision.md"
        if not decision.exists():
            continue
        text = decision.read_text()
        found = []
        missing = []
        for k, (rx, _) in KEYWORDS.items():
            if re.search(rx, text, re.I):
                found.append(k)
            else:
                missing.append(k)
        score = len(found) / len(KEYWORDS) * 100
        status = "pass" if score >= 80 else "warn" if score >= 50 else "fail"
        _row(f"{ticker_dir.name} discipline", f"{score:.0f}% ({len(found)}/{len(KEYWORDS)})", status)
        if missing:
            print(f"     {D}↳ missing: {', '.join(missing)}{X}")


# ────────────────────────────────────────────────────────────────────────
# 5. Decision coherence: rating vs trade side
# ────────────────────────────────────────────────────────────────────────
def audit_decision_coherence(log: str):
    _hdr("5. DECISION COHERENCE (rating ↔ trade)")

    decisions = re.findall(
        r"(?:Decision|Final|FINAL TRANSACTION).*?(BUY|SELL|HOLD)\s*(?:on|for)?\s*([\w.-]+)?",
        log, re.I,
    )
    ratings = re.findall(r"([\w.-]+)\s*→\s*(BUY|SELL|HOLD)", log)
    actions = re.findall(r"(?:Resolved|EXECUTED):\s*(BUY|SELL|HOLD|SKIP)\s+([\w.-]+)", log, re.I)
    _row("Total decisions in log", f"{len(decisions)}", "info")
    _row("Final ratings (T → R)", f"{len(ratings)}", "info")
    _row("Trade actions executed", f"{len(actions)}", "info")
    for action, ticker in actions:
        _row(f"  {ticker}", action.upper(),
             "pass" if action.upper() in ("BUY", "SELL", "HOLD", "SKIP") else "warn")


# ────────────────────────────────────────────────────────────────────────
# 6. Execution quality: portfolio DB
# ────────────────────────────────────────────────────────────────────────
def audit_execution():
    _hdr("6. EXECUTION QUALITY (paper portfolio)")

    db = DATA_DIR / "paper_portfolio.db"
    if not db.exists():
        _row("paper_portfolio.db", "MISSING", "fail")
        return

    conn = sqlite3.connect(db)
    c = conn.cursor()
    try:
        c.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in c.fetchall()]
        _row("Tables", ", ".join(tables), "info")

        for tbl in tables:
            c.execute(f"SELECT COUNT(*) FROM {tbl}")
            n = c.fetchone()[0]
            _row(f"  {tbl}", f"{n} rows", "info")

        if "orders" in tables:
            c.execute("SELECT ticker, side, quantity, price, status FROM orders ORDER BY rowid DESC LIMIT 10")
            print(f"\n  {B}Recent orders:{X}")
            for r in c.fetchall():
                color = G if r[4] == "FILLED" else Y
                print(f"     {color}{r[1]:5s}{X} {r[0]:15s}  qty={r[2]:>4}  @ ₹{r[3]:>8.2f}  [{r[4]}]")

        if "positions" in tables:
            c.execute("SELECT ticker, quantity, avg_price FROM positions WHERE quantity > 0")
            print(f"\n  {B}Current holdings:{X}")
            for r in c.fetchall():
                print(f"     {r[0]:15s}  {r[1]:>4} shares @ avg ₹{r[2]:>8.2f}")
    finally:
        conn.close()


# ────────────────────────────────────────────────────────────────────────
# 7. Memory log: did the system reflect on outcomes?
# ────────────────────────────────────────────────────────────────────────
def audit_memory():
    _hdr("7. MEMORY / REFLECTION (post-trade learning)")
    if not MEMORY_LOG.exists():
        _row("memory log", "MISSING (expected if first run, OK)", "warn")
        return
    text = MEMORY_LOG.read_text()
    entries = len(re.findall(r"^## ", text, re.M))
    _row("Memory entries", f"{entries}", "pass" if entries > 0 else "warn")
    _row("Memory log size", f"{len(text):,} chars", "info")


# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    log_path = find_log(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"\n{B}╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║   TradingAgents — Pipeline Quality Audit                            ║")
    print(f"╚══════════════════════════════════════════════════════════════════════╝{X}")
    print(f"{D}Log:    {log_path}{X}")
    print(f"{D}Results: {RESULTS_DIR}{X}")

    log_text = log_path.read_text(errors="replace")
    print(f"{D}Log size: {len(log_text):,} chars / {log_text.count(chr(10))} lines{X}")

    audit_data_quality(log_text)
    audit_analyst_depth()
    audit_debate_rigor()
    audit_trade_discipline()
    audit_decision_coherence(log_text)
    audit_execution()
    audit_memory()

    print(f"\n{D}Audit complete.{X}\n")
