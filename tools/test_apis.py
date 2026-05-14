"""Comprehensive API health check across all data vendors.

Tests every (method, vendor) combination and reports:
  ✅ OK     — returned non-trivial data
  ⚠️ EMPTY  — returned empty / "no data" string (fallback would trigger)
  ❌ ERROR  — raised an exception (missing API key, network, etc.)

Run from repo root:
    .venv/bin/python3 tools/test_apis.py [TICKER]

Defaults to RELIANCE.NS. Pass another NSE ticker to test a different stock.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta

# Quiet down library logs so the report stays readable.
logging.basicConfig(level=logging.CRITICAL)
import warnings  # noqa: E402
warnings.filterwarnings("ignore")

# Auto-detect proxy so RSS / yfinance work both at Walmart and at home.
from tradingagents.network import configure_network  # noqa: E402

configure_network()

from tradingagents.dataflows.interface import VENDOR_METHODS  # noqa: E402

# Per-method call signature (positional args only). Keep these in sync with
# the actual function signatures so the test exercises every vendor identically.
_CALL_ARGS = {
    "get_stock_data":           lambda t, s, e, c: (t, s, e),
    "get_indicators":           lambda t, s, e, c: (t, "rsi", c, 7),
    "get_fundamentals":         lambda t, s, e, c: (t, c),
    "get_balance_sheet":        lambda t, s, e, c: (t, "quarterly", c),
    "get_cashflow":             lambda t, s, e, c: (t, "quarterly", c),
    "get_income_statement":     lambda t, s, e, c: (t, "quarterly", c),
    "get_news":                 lambda t, s, e, c: (t, s, e),
    "get_global_news":          lambda t, s, e, c: (c, 7, 5),
    "get_insider_transactions": lambda t, s, e, c: (t,),
}


def _classify(result) -> tuple[str, int, str]:
    """Bucket a vendor result into (status, size, preview)."""
    text = str(result) if result is not None else ""
    size = len(text)
    preview = text.replace("\n", " ").strip()[:55]
    lower = text.lower()
    empty_markers = ("no ", "not found", "no data", "unavailable", "error ")
    is_empty = (
        size == 0
        or (size < 200 and any(lower.startswith(m) or m in lower for m in empty_markers))
    )
    status = "⚠️  EMPTY" if is_empty else "✅ OK"
    return status, size, preview


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "RELIANCE.NS"
    today = datetime.now()
    end = today.strftime("%Y-%m-%d")
    start = (today - timedelta(days=14)).strftime("%Y-%m-%d")
    curr = end

    print(f"\nAPI health check — ticker={ticker}, dates={start}..{end}\n")
    print(f"{'Method':<26} {'Vendor':<14} {'Status':<10} {'Size':>8}  Preview / Error")
    print("=" * 110)

    summary: dict[str, int] = {"ok": 0, "empty": 0, "error": 0}

    for method, vendors in VENDOR_METHODS.items():
        if method not in _CALL_ARGS:
            continue
        args_fn = _CALL_ARGS[method]
        args = args_fn(ticker, start, end, curr)

        for vendor, impl in vendors.items():
            impl_func = impl[0] if isinstance(impl, list) else impl
            try:
                result = impl_func(*args)
                status, size, preview = _classify(result)
                if status.startswith("✅"):
                    summary["ok"] += 1
                else:
                    summary["empty"] += 1
                print(f"{method:<26} {vendor:<14} {status:<10} {size:>8}  {preview}")
            except Exception as exc:
                err = str(exc).replace("\n", " ")[:60]
                summary["error"] += 1
                print(f"{method:<26} {vendor:<14} {'❌ ERROR':<10} {'-':>8}  {err}")

    total = sum(summary.values())
    print("\n" + "=" * 110)
    print(
        f"Summary: {summary['ok']} OK, {summary['empty']} empty, "
        f"{summary['error']} errors  ({total} calls)"
    )
    # Non-zero exit only if every single call failed — empties are
    # expected for vendors that don't cover Indian stocks.
    return 0 if summary["ok"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
