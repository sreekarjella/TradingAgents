"""Trading Dashboard — FastAPI + HTMX + Tailwind + Chart.js.

Zerodha-inspired layout with Walmart colors.
Run:  python -m dashboard.app
  or: uvicorn dashboard.app:app --reload --port 8501
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Generator

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

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
        return "text-gray-500"
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

def _header_context() -> dict[str, Any]:
    """Portfolio summary for the sticky header."""
    config_cash = query_one(PORTFOLIO_DB, "SELECT value FROM config WHERE key='cash'")
    cash = float(config_cash["value"]) if config_cash else 0.0

    config_cap = query_one(PORTFOLIO_DB, "SELECT value FROM config WHERE key='initial_capital'")
    initial_capital = float(config_cap["value"]) if config_cap else 1_000_000.0

    holdings = query(PORTFOLIO_DB, "SELECT * FROM holdings WHERE quantity > 0")

    # Estimate current value: use last order price per ticker as LTP proxy
    holdings_value = 0.0
    for h in holdings:
        last_order = query_one(
            PORTFOLIO_DB,
            "SELECT price FROM orders WHERE ticker=? AND status='FILLED' ORDER BY created_at DESC LIMIT 1",
            (h["ticker"],),
        )
        ltp = last_order["price"] if last_order else h["avg_price"]
        holdings_value += h["quantity"] * ltp

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
    """Portfolio holdings and allocation."""
    hdr = _header_context()
    holdings = query(PORTFOLIO_DB, "SELECT * FROM holdings WHERE quantity > 0 ORDER BY invested_value DESC")

    enriched: list[dict[str, Any]] = []
    for h in holdings:
        last_order = query_one(
            PORTFOLIO_DB,
            "SELECT price FROM orders WHERE ticker=? AND status='FILLED' ORDER BY created_at DESC LIMIT 1",
            (h["ticker"],),
        )
        ltp = last_order["price"] if last_order else h["avg_price"]
        current_value = h["quantity"] * ltp
        pnl = current_value - h["invested_value"]
        pnl_pct = (pnl / h["invested_value"] * 100) if h["invested_value"] else 0.0
        alloc = (current_value / hdr["total_value"] * 100) if hdr["total_value"] else 0.0
        enriched.append({
            **h,
            "ltp": ltp,
            "current_value": current_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "allocation": alloc,
        })

    return templates.TemplateResponse(request, "portfolio.html", {
        "page": "portfolio",
        "header": hdr,
        "holdings": enriched,
    })


@app.get("/orders", response_class=HTMLResponse)
async def page_orders(
    request: Request,
    ticker: str = Query("ALL", alias="ticker"),
    side: str = Query("ALL", alias="side"),
    status: str = Query("ALL", alias="status"),
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

    sql += " ORDER BY created_at DESC"
    orders = query(PORTFOLIO_DB, sql, tuple(params))

    # Summary stats
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
        "total_orders": total_orders,
        "total_buys": total_buys,
        "total_sells": total_sells,
        "total_realized_pnl": total_realized_pnl,
    })


@app.get("/history", response_class=HTMLResponse)
async def page_history(request: Request) -> HTMLResponse:
    """Performance charts from daily snapshots."""
    snapshots = query(PORTFOLIO_DB, "SELECT * FROM daily_snapshots ORDER BY date ASC")

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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8501, reload=True)
