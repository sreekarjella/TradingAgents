# MLX Backend for TradingAgents 🍎

Run the trading pipeline on Apple Silicon using [MLX](https://github.com/ml-explore/mlx)
instead of Ollama. MLX is Apple's native ML framework — it uses unified
memory (no CPU→GPU copies) and Metal GPU acceleration for faster inference.

## Why MLX?

| Metric | Ollama (llama.cpp) | MLX |
|---|---|---|
| Memory model | CPU+GPU split | Unified (zero-copy) |
| Prefill speed | Good | **~2× faster** |
| Generation speed | ~26 tok/s (14B) | ~30 tok/s (14B) |
| Speculative decoding | ❌ Not available | ✅ Built-in |
| Tool calling | ✅ Native | ✅ Via chat templates |

## Quick Start

```bash
# 1. Download models (~30 GB total, one-time)
./mlx/download.sh

# 2. Start both MLX servers
./mlx/start.sh

# 3. Update config.toml — copy from mlx/config_mlx.toml:
#    provider = "mlx"
#    quick_backend_url = "http://localhost:8081/v1"
#    deep_backend_url  = "http://localhost:8082/v1"

# 4. Run the pipeline as normal
python -m tradingagents.trading.daily_runner
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  TradingAgents Pipeline                                 │
│                                                         │
│  ┌──────────┐  quick_backend_url   ┌────────────────┐  │
│  │ Analysts │ ──────────────────── │ MLX Server #1  │  │
│  │ Debaters │  :8081/v1            │ Qwen3-14B-4bit │  │
│  │ Trader   │                      │ + 0.6B draft   │  │
│  └──────────┘                      └────────────────┘  │
│                                                         │
│  ┌──────────┐  deep_backend_url    ┌────────────────┐  │
│  │ Research │ ──────────────────── │ MLX Server #2  │  │
│  │ Manager  │  :8082/v1            │ Qwen3-32B-4bit │  │
│  │ Portfolio│                      │                │  │
│  │ Manager  │                      └────────────────┘  │
│  └──────────┘                                           │
└─────────────────────────────────────────────────────────┘
```

## Commands

| Command | Description |
|---|---|
| `./mlx/download.sh` | Download all 3 models |
| `./mlx/download.sh --quick` | Download quick model only |
| `./mlx/download.sh --deep` | Download deep model only |
| `./mlx/download.sh --draft` | Download draft model only |
| `./mlx/start.sh` | Start both servers |
| `./mlx/start.sh --speculative` | Start with speculative decoding |
| `./mlx/start.sh --quick-only` | Start quick server only |
| `./mlx/stop.sh` | Stop all servers |
| `python mlx/benchmark.py` | Run Ollama vs MLX speed test |

## Speculative Decoding

Speculative decoding uses a small "draft" model (0.6B) to predict
tokens ahead of time, then the main model (14B) verifies them in
a single batch. This can speed up generation by 1.5-2× when the
draft model's predictions are accurate (which they often are for
same-family models like Qwen3).

```bash
# Start with speculative decoding enabled
./mlx/start.sh --speculative
```

## Memory Budget

| Model | Size | Role |
|---|---|---|
| Qwen3-14B-4bit | ~9.3 GB | Quick thinker (analysts) |
| Qwen3-32B-4bit | ~20 GB | Deep thinker (managers) |
| Qwen3-0.6B-4bit | ~0.4 GB | Draft (speculative) |
| KV cache | ~4-6 GB | Context memory |
| System + OS | ~6 GB | macOS overhead |
| **Total** | **~40-42 GB** | **Fits in 48 GB M4 Pro** |

## Switching Back to Ollama

```bash
# 1. Stop MLX servers
./mlx/stop.sh

# 2. Restore config.toml
provider = "ollama"
quick_backend_url = ""
deep_backend_url = ""
```

## Troubleshooting

**Server won't start / model download fails:**
- Ensure you're on Walmart VPN (HuggingFace needs proxy)
- Check logs: `tail -f mlx/logs/quick.log`

**Out of memory:**
- Close other GPU-heavy apps (browsers, etc.)
- Try `--quick-only` first to test with just the 14B model

**Slow first request:**
- First request triggers model loading (~10-20s). Subsequent
  requests are fast. This is normal.

**Port conflict:**
- Port 8080 is reserved for Teams. We use 8081/8082.
- Check: `lsof -i :8081` / `lsof -i :8082`
