"""Trading Dashboard — FastAPI + HTMX + Tailwind + Chart.js.

Zerodha-inspired layout with Walmart colors.
Run:  python -m dashboard.app
  or: uvicorn dashboard.app:app --reload --port 8501
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Generator

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel

from .live_prices import fetch_live_prices

# ---------------------------------------------------------------------------
# Path setup — DBs live at ../data/ relative to this file
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"
PORTFOLIO_DB = DATA_DIR / "paper_portfolio.db"
RUN_TRACKER_DB = DATA_DIR / "run_tracker.db"
TEMPLATES_DIR = BASE_DIR / "templates"

app = FastAPI(title="Trading Dashboard", docs_url="/docs")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ---------------------------------------------------------------------------
# Jinja2 custom filters
# ---------------------------------------------------------------------------

def fmt_inr(value: float | None) -> str:
    """Format number as Indian Rupee with commas."""
    if value is None:
        return "₹0.00"
    sign = "-" if value < 0 else ""
    val = abs(value)
    s = f"{val:,.2f}"
    return f"{sign}₹{s}"


def fmt_pct(value: float | None) -> str:
    """Format as percentage."""
    if value is None:
        return "0.00%"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def fmt_duration(secs: float | None) -> str:
    """Format seconds into human-readable duration."""
    if secs is None:
        return "—"
    if secs < 60:
        return f"{secs:.1f}s"
    mins = int(secs // 60)
    remaining = secs % 60
    return f"{mins}m {remaining:.0f}s"


def pnl_color(value: float | None) -> str:
    """Return Walmart-themed CSS class for profit/loss."""
    if value is None or value == 0:
        return "text-gray-500 dark:text-dark-muted"
    return "text-[#2a8703]" if value > 0 else "text-[#ea1100]"


def rating_badge(rating: str) -> Markup:
    """Return HTML badge for a rating."""
    r = (rating or "").strip().lower()
    color_map = {
        "buy": ("bg-[#2a8703]", "text-white"),
        "strong buy": ("bg-[#2a8703]", "text-white"),
        "overweight": ("bg-[#d4edda]", "text-[#2a8703]"),
        "sell": ("bg-[#ea1100]", "text-white"),
        "strong sell": ("bg-[#ea1100]", "text-white"),
        "underweight": ("bg-[#ffecd2]", "text-[#995213]"),
        "hold": ("bg-[#0053e2]", "text-white"),
        "error": ("bg-[#ea1100]", "text-white"),
        "duplicate": ("bg-[#d1d1d1]", "text-[#2e2f32]"),
    }
    bg, fg = color_map.get(r, ("bg-[#d1d1d1]", "text-[#2e2f32]"))
    label = rating or "N/A"
    return Markup(
        f'<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold '
        f'{bg} {fg}">{label}</span>'
    )


def side_badge(side: str) -> Markup:
    """Buy/Sell badge."""
    if side == "BUY":
        return Markup('<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-[#2a8703] text-white">BUY</span>')
    return Markup('<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-[#ea1100] text-white">SELL</span>')


def status_badge(status: str) -> Markup:
    """FILLED / REJECTED badge."""
    if status == "FILLED":
        return Markup('<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-[#d4edda] text-[#2a8703]">FILLED</span>')
    return Markup('<span class="inline-block px-2 py-0.5 rounded text-xs font-semibold bg-[#fdd] text-[#ea1100]">REJECTED</span>')


# Register filters
templates.env.filters["fmt_inr"] = fmt_inr
templates.env.filters["fmt_pct"] = fmt_pct
templates.env.filters["fmt_duration"] = fmt_duration
templates.env.filters["pnl_color"] = pnl_color
templates.env.globals["rating_badge"] = rating_badge
templates.env.globals["side_badge"] = side_badge
templates.env.globals["status_badge"] = status_badge


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

@contextmanager
def get_db(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a SQLite connection with row-factory for dict-like access."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def query(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Execute a SELECT and return list of dicts."""
    if not db_path.exists():
        return []
    with get_db(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def query_one(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Execute a SELECT and return first row as dict, or None."""
    results = query(db_path, sql, params)
    return results[0] if results else None


# ---------------------------------------------------------------------------
# Shared context — header data for every page
# ---------------------------------------------------------------------------

def _last_order_prices(tickers: list[str]) -> dict[str, float]:
    """Stale-but-cheap fallback: most recent FILLED order price per ticker.

    Used when live yfinance data isn't available (no internet, market
    closed, etc.). Returns ``{}`` when there are no tickers.
    """
    if not tickers:
        return {}
    placeholders = ",".join("?" * len(tickers))
    rows = query(
        PORTFOLIO_DB,
        f"""
            SELECT ticker, price
            FROM (
                SELECT ticker, price, created_at,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY created_at DESC) AS rn
                FROM orders
                WHERE status='FILLED' AND ticker IN ({placeholders})
            )
            WHERE rn = 1
        """,
        tuple(tickers),
    )
    return {r["ticker"]: r["price"] for r in rows}


def _resolve_ltp(
    holding: dict[str, Any],
    live_prices: dict[str, float],
    fallback_prices: dict[str, float],
) -> float:
    """Pick the best available last-traded-price for *holding*.

    Preference order: live (yfinance) → last filled order → cost basis.
    Cost basis as last resort means a brand-new position with no live
    feed shows zero P&L instead of crashing.
    """
    ticker = holding["ticker"]
    return (
        live_prices.get(ticker)
        or fallback_prices.get(ticker)
        or holding["avg_price"]
    )


def _enrich_holdings(
    holdings: list[dict[str, Any]],
    total_value: float,
    live_prices: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Add ltp / current_value / pnl / pnl_pct / allocation columns.

    Single source of truth for the holdings shape used by both the page
    template and the refresh partial — the previous code duplicated this
    logic between ``_header_context`` and ``page_portfolio``.
    """
    live = live_prices or {}
    fallback = _last_order_prices([h["ticker"] for h in holdings])
    enriched: list[dict[str, Any]] = []
    for h in holdings:
        ltp = _resolve_ltp(h, live, fallback)
        current_value = h["quantity"] * ltp
        pnl = current_value - h["invested_value"]
        pnl_pct = (pnl / h["invested_value"] * 100) if h["invested_value"] else 0.0
        alloc = (current_value / total_value * 100) if total_value else 0.0
        enriched.append({
            **h,
            "ltp": ltp,
            "current_value": current_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "allocation": alloc,
        })
    return enriched


def _header_context(live_prices: dict[str, float] | None = None) -> dict[str, Any]:
    """Portfolio summary for the sticky header.

    When *live_prices* is provided (from the Refresh action), the totals
    reflect real-time yfinance data. Otherwise we fall back to the last
    filled order price per ticker, which is what the page has shown
    historically.
    """
    config_cash = query_one(PORTFOLIO_DB, "SELECT value FROM config WHERE key='cash'")
    cash = float(config_cash["value"]) if config_cash else 0.0

    config_cap = query_one(PORTFOLIO_DB, "SELECT value FROM config WHERE key='initial_capital'")
    initial_capital = float(config_cap["value"]) if config_cap else 1_000_000.0

    holdings = query(PORTFOLIO_DB, "SELECT * FROM holdings WHERE quantity > 0")

    live = live_prices or {}
    fallback = _last_order_prices([h["ticker"] for h in holdings])
    holdings_value = sum(
        h["quantity"] * _resolve_ltp(h, live, fallback) for h in holdings
    )

    total_value = cash + holdings_value
    invested = sum(h["invested_value"] for h in holdings)
    total_pnl = total_value - initial_capital
    total_pnl_pct = (total_pnl / initial_capital * 100) if initial_capital else 0.0

    return {
        "cash": cash,
        "invested": invested,
        "holdings_value": holdings_value,
        "total_value": total_value,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "initial_capital": initial_capital,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
@app.get("/today", response_class=HTMLResponse)
async def page_today(request: Request) -> HTMLResponse:
    """Today's pipeline run results."""
    today_str = date.today().isoformat()

    runs_today = query(
        RUN_TRACKER_DB,
        "SELECT * FROM run_log WHERE date = ? ORDER BY created_at DESC",
        (today_str,),
    )

    total_runs = len(runs_today)
    successes = sum(1 for r in runs_today if not r.get("error"))
    errors = sum(1 for r in runs_today if r.get("error"))
    dupes = sum(1 for r in runs_today if "duplicate" in (r.get("error") or "").lower())
    total_runtime = sum(r.get("duration_secs", 0) or 0 for r in runs_today)

    return templates.TemplateResponse(request, "today.html", {
        "page": "today",
        "header": _header_context(),
        "today_str": today_str,
        "runs": runs_today,
        "total_runs": total_runs,
        "successes": successes,
        "errors": errors,
        "dupes": dupes,
        "total_runtime": total_runtime,
    })


@app.get("/portfolio", response_class=HTMLResponse)
async def page_portfolio(request: Request) -> HTMLResponse:
    """Portfolio holdings and allocation (initial render — stale prices).

    The Refresh button on the page triggers ``/api/portfolio/refresh``
    which fetches live prices and swaps in the updated body.
    """
    hdr = _header_context()
    holdings = query(
        PORTFOLIO_DB,
        "SELECT * FROM holdings WHERE quantity > 0 ORDER BY invested_value DESC",
    )
    enriched = _enrich_holdings(holdings, hdr["total_value"])
    return templates.TemplateResponse(request, "portfolio.html", {
        "page": "portfolio",
        "header": hdr,
        "holdings": enriched,
        "prices_are_live": False,
        "refreshed_at": None,
    })


@app.post("/api/portfolio/refresh", response_class=HTMLResponse)
async def api_portfolio_refresh(request: Request) -> HTMLResponse:
    """Fetch live prices for every held ticker and re-render the body.

    Returns the ``_portfolio_body.html`` partial so HTMX can swap it in
    without a full page reload.
    """
    from datetime import datetime

    holdings = query(
        PORTFOLIO_DB,
        "SELECT * FROM holdings WHERE quantity > 0 ORDER BY invested_value DESC",
    )
    tickers = [h["ticker"] for h in holdings]
    live = fetch_live_prices(tickers)

    hdr = _header_context(live_prices=live)
    enriched = _enrich_holdings(holdings, hdr["total_value"], live_prices=live)

    return templates.TemplateResponse(request, "_portfolio_body.html", {
        "page": "portfolio",
        "header": hdr,
        "holdings": enriched,
        "prices_are_live": bool(live),
        "live_count": len(live),
        "total_count": len(tickers),
        "refreshed_at": datetime.now().strftime("%H:%M:%S"),
    })


@app.get("/orders", response_class=HTMLResponse)
async def page_orders(
    request: Request,
    ticker: str = Query("ALL", alias="ticker"),
    side: str = Query("ALL", alias="side"),
    status: str = Query("ALL", alias="status"),
    date_from: str = Query("", alias="date_from"),
    date_to: str = Query("", alias="date_to"),
) -> HTMLResponse:
    """Full order history with filters."""
    sql = "SELECT * FROM orders WHERE 1=1"
    params: list[Any] = []

    if ticker != "ALL":
        sql += " AND ticker = ?"
        params.append(ticker)
    if side != "ALL":
        sql += " AND side = ?"
        params.append(side)
    if status != "ALL":
        sql += " AND status = ?"
        params.append(status)
    if date_from:
        sql += " AND date(created_at) >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND date(created_at) <= ?"
        params.append(date_to)

    sql += " ORDER BY created_at DESC"
    orders = query(PORTFOLIO_DB, sql, tuple(params))

    # Summary stats (unfiltered)
    all_orders = query(PORTFOLIO_DB, "SELECT * FROM orders")
    total_orders = len(all_orders)
    total_buys = sum(1 for o in all_orders if o["side"] == "BUY")
    total_sells = sum(1 for o in all_orders if o["side"] == "SELL")
    total_realized_pnl = sum(o.get("pnl") or 0 for o in all_orders)

    # Distinct tickers for filter dropdown
    tickers = query(PORTFOLIO_DB, "SELECT DISTINCT ticker FROM orders ORDER BY ticker")
    ticker_list = [t["ticker"] for t in tickers]

    return templates.TemplateResponse(request, "orders.html", {
        "page": "orders",
        "header": _header_context(),
        "orders": orders,
        "ticker_list": ticker_list,
        "filter_ticker": ticker,
        "filter_side": side,
        "filter_status": status,
        "filter_date_from": date_from,
        "filter_date_to": date_to,
        "total_orders": total_orders,
        "total_buys": total_buys,
        "total_sells": total_sells,
        "total_realized_pnl": total_realized_pnl,
    })


@app.get("/history", response_class=HTMLResponse)
async def page_history(
    request: Request,
    range: str = Query("ALL", alias="range"),
    benchmark: str = Query("NIFTY50", alias="benchmark"),
) -> HTMLResponse:
    """Performance charts from daily snapshots with time range filter."""
    snapshots = query(PORTFOLIO_DB, "SELECT * FROM daily_snapshots ORDER BY date ASC")

    # ── Time range filter ────────────────────────────────────────
    range_days_map = {
        "1W": 7, "1M": 30, "3M": 90, "6M": 180, "1Y": 365,
    }
    if range in range_days_map and snapshots:
        cutoff = (date.today() - timedelta(days=range_days_map[range])).isoformat()
        snapshots = [s for s in snapshots if s["date"] >= cutoff]

    # ── Benchmark label mapping ──────────────────────────────────
    benchmark_map = {
        "NIFTY50":    {"ticker": "^NSEI",     "name": "NIFTY 50"},
        "SENSEX":     {"ticker": "^BSESN",    "name": "SENSEX"},
        "NIFTYBANK":  {"ticker": "^NSEBANK",  "name": "NIFTY Bank"},
        "NIFTYIT":    {"ticker": "^CNXIT",    "name": "NIFTY IT"},
        "NIFTYMIDCAP":{"ticker": "NIFTY_MID_SELECT.NS", "name": "NIFTY Midcap"},
    }
    bm_info = benchmark_map.get(benchmark, benchmark_map["NIFTY50"])

    dates = [s["date"] for s in snapshots]
    total_values = [s["total_value"] for s in snapshots]
    benchmark_values = [s.get("benchmark_value") for s in snapshots]
    daily_returns = [s.get("daily_return_pct", 0) or 0 for s in snapshots]

    # Cumulative stats
    total_return_pct = 0.0
    alpha = 0.0
    max_drawdown = 0.0

    if snapshots:
        first_val = snapshots[0]["total_value"]
        last_val = snapshots[-1]["total_value"]
        total_return_pct = ((last_val - first_val) / first_val * 100) if first_val else 0

        first_bm = snapshots[0].get("benchmark_value")
        last_bm = snapshots[-1].get("benchmark_value")
        if first_bm and last_bm:
            bm_return = (last_bm - first_bm) / first_bm * 100
            alpha = total_return_pct - bm_return

        # Max drawdown
        peak = 0.0
        for s in snapshots:
            v = s["total_value"]
            if v > peak:
                peak = v
            dd = (peak - v) / peak * 100 if peak else 0
            if dd > max_drawdown:
                max_drawdown = dd

    return templates.TemplateResponse(request, "history.html", {
        "page": "history",
        "header": _header_context(),
        "has_data": len(snapshots) > 0,
        "dates": dates,
        "total_values": total_values,
        "benchmark_values": benchmark_values,
        "daily_returns": daily_returns,
        "total_return_pct": total_return_pct,
        "alpha": alpha,
        "max_drawdown": max_drawdown,
        "snapshot_count": len(snapshots),
        "selected_range": range,
        "selected_benchmark": benchmark,
        "benchmark_name": bm_info["name"],
        "benchmark_map": benchmark_map,
    })


@app.get("/runs", response_class=HTMLResponse)
async def page_runs(
    request: Request,
    page_num: int = Query(1, alias="page", ge=1),
) -> HTMLResponse:
    """All run history, grouped by date."""
    page_size = 50
    offset = (page_num - 1) * page_size

    total_row = query_one(RUN_TRACKER_DB, "SELECT COUNT(*) as cnt FROM run_log")
    total_count = total_row["cnt"] if total_row else 0

    runs = query(
        RUN_TRACKER_DB,
        "SELECT * FROM run_log ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    )

    # Group by date
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in runs:
        d = r["date"]
        grouped.setdefault(d, []).append(r)

    # Stats per date
    date_stats: dict[str, dict[str, Any]] = {}
    for d, items in grouped.items():
        count = len(items)
        avg_dur = sum(i.get("duration_secs", 0) or 0 for i in items) / count if count else 0
        success_count = sum(1 for i in items if not i.get("error"))
        rate = (success_count / count * 100) if count else 0
        date_stats[d] = {"count": count, "avg_duration": avg_dur, "success_rate": rate}

    total_pages = max(1, (total_count + page_size - 1) // page_size)

    return templates.TemplateResponse(request, "runs.html", {
        "page": "runs",
        "header": _header_context(),
        "grouped": grouped,
        "date_stats": date_stats,
        "total_count": total_count,
        "page_num": page_num,
        "total_pages": total_pages,
    })


@app.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request) -> HTMLResponse:
    """Settings page with DB reset controls."""
    stats = {
        "orders": (query_one(PORTFOLIO_DB, "SELECT COUNT(*) as n FROM orders") or {}).get("n", 0),
        "holdings": (query_one(PORTFOLIO_DB, "SELECT COUNT(*) as n FROM holdings WHERE quantity > 0") or {}).get("n", 0),
        "snapshots": (query_one(PORTFOLIO_DB, "SELECT COUNT(*) as n FROM daily_snapshots") or {}).get("n", 0),
        "run_logs": (query_one(RUN_TRACKER_DB, "SELECT COUNT(*) as n FROM run_log") or {}).get("n", 0),
    }
    return templates.TemplateResponse(request, "settings.html", {
        "page": "settings",
        "header": _header_context(),
        "stats": stats,
    })


class ResetRequest(BaseModel):
    initial_capital: float = 1_000_000.0


@app.post("/api/reset")
async def api_reset(body: ResetRequest) -> JSONResponse:
    """Wipe all trading data and reset to fresh state."""
    capital = max(body.initial_capital, 10_000)  # Floor at ₹10K

    try:
        # Reset portfolio DB
        with get_db(PORTFOLIO_DB) as conn:
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM holdings")
            conn.execute("DELETE FROM daily_snapshots")
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('cash', ?)", (str(capital),))
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES ('initial_capital', ?)", (str(capital),))
            conn.commit()

        # Reset run tracker DB
        if RUN_TRACKER_DB.exists():
            with get_db(RUN_TRACKER_DB) as conn:
                conn.execute("DELETE FROM run_log")
                conn.commit()

        return JSONResponse({
            "success": True,
            "message": f"All data cleared. Starting fresh with ₹{capital:,.0f}",
        })
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/seed")
async def api_seed() -> JSONResponse:
    """Seed demo data for dashboard testing."""
    try:
        from dashboard.seed_demo_data import seed_all
        result = seed_all()
        return JSONResponse({"success": True, "message": result})
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


# ---------------------------------------------------------------------------
# Pipeline + Log viewer routes (factored into separate router)
# ---------------------------------------------------------------------------

from dashboard.routes_pipeline import router as pipeline_router

app.include_router(pipeline_router)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8501, reload=True)
