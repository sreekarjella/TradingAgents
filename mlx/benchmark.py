"""Benchmark: Ollama vs MLX server — head-to-head speed comparison.

Sends identical prompts to both backends and compares prefill speed,
generation speed, and total latency. Uses the same OpenAI-compatible
API that the pipeline uses, so results reflect real-world performance.

Usage:
    # Ensure both Ollama and MLX servers are running, then:
    python mlx/benchmark.py

    # Test only the quick model (14B):
    python mlx/benchmark.py --quick-only

    # Test only the deep model (32B):
    python mlx/benchmark.py --deep-only

    # Custom number of runs:
    python mlx/benchmark.py --runs 5
"""

import argparse
import json
import statistics
import time

import httpx

# ── Endpoints ───────────────────────────────────────────────────────────

OLLAMA_URL = "http://localhost:11434/v1/chat/completions"
MLX_QUICK_URL = "http://localhost:8081/v1/chat/completions"
MLX_DEEP_URL = "http://localhost:8082/v1/chat/completions"

# ── Test Prompts ────────────────────────────────────────────────────────
# These mirror what the pipeline actually sends — financial analysis tasks

QUICK_PROMPT = {
    "model": "qwen3:14b",
    "messages": [
        {
            "role": "system",
            "content": (
                "You are a financial analyst. Analyze the given stock data "
                "and provide a concise technical assessment."
            ),
        },
        {
            "role": "user",
            "content": (
                "Analyze RELIANCE.NS: Current price ₹2,850, 52-week high ₹3,024, "
                "52-week low ₹2,221. P/E ratio 28.5, EPS ₹100. Volume today: "
                "12M shares vs 20-day avg 8M. RSI: 65. MACD: bullish crossover "
                "3 days ago. Moving averages: above 50-day, above 200-day. "
                "FII bought ₹2,500 Cr in the sector this week. Recent news: "
                "Jio tariff hike announced, refinery margins improving. "
                "Provide a 3-sentence technical outlook."
            ),
        },
    ],
    "max_tokens": 256,
    "temperature": 0.7,
}

DEEP_PROMPT = {
    "model": "qwen3:32b",
    "messages": [
        {
            "role": "system",
            "content": (
                "You are a senior portfolio manager. Synthesize the research "
                "and provide a final investment decision with reasoning."
            ),
        },
        {
            "role": "user",
            "content": (
                "Based on the following analysis:\n\n"
                "BULL CASE: Strong volume breakout, positive FII flows, "
                "improving margins, Jio tariff hike will boost ARPU by 15%. "
                "Technical setup is bullish with MACD crossover.\n\n"
                "BEAR CASE: P/E of 28.5 is above sector median of 22. "
                "Global crude prices rising may compress refinery margins. "
                "INR weakening against USD increases import costs.\n\n"
                "RISK ASSESSMENT: Moderate risk. Key monitoring points are "
                "crude oil prices and FII flow sustainability.\n\n"
                "Provide your final decision: Buy, Hold, Sell, Overweight, "
                "or Underweight. Include confidence level and key rationale."
            ),
        },
    ],
    "max_tokens": 512,
    "temperature": 0.7,
}

# ── Benchmark Logic ────────────────────────────────────────────────────


def _send_request(url: str, payload: dict) -> dict:
    """Send a chat completion request and measure timing."""
    client = httpx.Client(proxy=None, verify=False, timeout=300.0)

    start = time.perf_counter()
    try:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return {"error": str(e), "elapsed": 0, "tokens": 0}
    finally:
        client.close()

    elapsed = time.perf_counter() - start
    data = resp.json()
    usage = data.get("usage", {})

    return {
        "elapsed": elapsed,
        "prompt_tokens": usage.get("prompt_tokens", 0),
        "completion_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "content": data["choices"][0]["message"]["content"][:100],
    }


def _run_benchmark(
    name: str,
    ollama_url: str,
    mlx_url: str,
    payload: dict,
    runs: int,
) -> None:
    """Run N iterations against both backends and print comparison."""
    print(f"\n{'━' * 70}")
    print(f"  {name}")
    print(f"{'━' * 70}")

    ollama_times = []
    mlx_times = []
    ollama_tps = []
    mlx_tps = []

    for i in range(runs):
        print(f"\n  Run {i + 1}/{runs}:")

        # Ollama
        print(f"    Ollama  → ", end="", flush=True)
        r_ollama = _send_request(ollama_url, payload)
        if "error" in r_ollama:
            print(f"ERROR: {r_ollama['error']}")
        else:
            tps = r_ollama["completion_tokens"] / r_ollama["elapsed"] if r_ollama["elapsed"] > 0 else 0
            ollama_times.append(r_ollama["elapsed"])
            ollama_tps.append(tps)
            print(
                f"{r_ollama['elapsed']:.1f}s | "
                f"{r_ollama['completion_tokens']} tokens | "
                f"{tps:.1f} tok/s"
            )

        # MLX
        print(f"    MLX     → ", end="", flush=True)
        r_mlx = _send_request(mlx_url, payload)
        if "error" in r_mlx:
            print(f"ERROR: {r_mlx['error']}")
        else:
            tps = r_mlx["completion_tokens"] / r_mlx["elapsed"] if r_mlx["elapsed"] > 0 else 0
            mlx_times.append(r_mlx["elapsed"])
            mlx_tps.append(tps)
            print(
                f"{r_mlx['elapsed']:.1f}s | "
                f"{r_mlx['completion_tokens']} tokens | "
                f"{tps:.1f} tok/s"
            )

    # Summary
    if ollama_times and mlx_times:
        print(f"\n  {'─' * 66}")
        print(f"  SUMMARY ({runs} runs):")
        print(f"  {'─' * 66}")

        o_avg = statistics.mean(ollama_times)
        m_avg = statistics.mean(mlx_times)
        o_tps_avg = statistics.mean(ollama_tps)
        m_tps_avg = statistics.mean(mlx_tps)
        speedup = o_avg / m_avg if m_avg > 0 else 0

        print(f"  {'Metric':<25s} {'Ollama':>12s} {'MLX':>12s} {'Winner':>12s}")
        print(f"  {'─' * 66}")
        print(
            f"  {'Avg latency':<25s} "
            f"{o_avg:>10.1f}s "
            f"{m_avg:>10.1f}s "
            f"{'MLX' if m_avg < o_avg else 'Ollama':>12s}"
        )
        print(
            f"  {'Avg tok/s':<25s} "
            f"{o_tps_avg:>10.1f}  "
            f"{m_tps_avg:>10.1f}  "
            f"{'MLX' if m_tps_avg > o_tps_avg else 'Ollama':>12s}"
        )
        print(
            f"  {'Speedup':<25s} "
            f"{'baseline':>12s} "
            f"{speedup:>10.2f}x "
            f"{'🚀' if speedup > 1 else '':>12s}"
        )

        if runs > 1 and len(ollama_times) > 1 and len(mlx_times) > 1:
            print(
                f"  {'Std dev (latency)':<25s} "
                f"{statistics.stdev(ollama_times):>10.2f}s "
                f"{statistics.stdev(mlx_times):>10.2f}s"
            )


def main():
    parser = argparse.ArgumentParser(description="Benchmark Ollama vs MLX")
    parser.add_argument("--runs", type=int, default=3, help="Number of runs per test")
    parser.add_argument("--quick-only", action="store_true", help="Test quick model only")
    parser.add_argument("--deep-only", action="store_true", help="Test deep model only")
    args = parser.parse_args()

    print("\n" + "═" * 70)
    print("  Ollama vs MLX — Head-to-Head Benchmark")
    print("═" * 70)
    print(f"  Runs per test: {args.runs}")
    print(f"  Ollama:  {OLLAMA_URL}")
    print(f"  MLX:     Quick={MLX_QUICK_URL}  Deep={MLX_DEEP_URL}")

    if not args.deep_only:
        _run_benchmark(
            name="QUICK MODEL (14B) — Financial Analysis",
            ollama_url=OLLAMA_URL,
            mlx_url=MLX_QUICK_URL,
            payload=QUICK_PROMPT,
            runs=args.runs,
        )

    if not args.quick_only:
        _run_benchmark(
            name="DEEP MODEL (32B) — Portfolio Decision",
            ollama_url=OLLAMA_URL,
            mlx_url=MLX_DEEP_URL,
            payload=DEEP_PROMPT,
            runs=args.runs,
        )

    print(f"\n{'═' * 70}")
    print("  Benchmark complete!")
    print(f"{'═' * 70}\n")


if __name__ == "__main__":
    main()
