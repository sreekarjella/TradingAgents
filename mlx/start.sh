#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# MLX Server Launcher — starts both quick & deep model servers
#
# Usage:
#   ./mlx/start.sh                   # Start both servers (default)
#   ./mlx/start.sh --speculative     # Enable speculative decoding on quick model
#   ./mlx/start.sh --quick-only      # Start only the quick model server
#   ./mlx/start.sh --deep-only       # Start only the deep model server
#
# Ports:
#   Quick model (14B) → http://localhost:8081
#   Deep  model (32B) → http://localhost:8082
#
# After starting, update config.toml:
#   provider = "mlx"
#   quick_backend_url = "http://localhost:8081/v1"
#   deep_backend_url  = "http://localhost:8082/v1"
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$PROJECT_DIR/.venv/bin"
MLX_SERVER="$VENV/python3 -m mlx_lm server"

# Model repos (pre-quantized 4-bit MLX format from HuggingFace)
QUICK_MODEL="mlx-community/Qwen3-14B-4bit"
DEEP_MODEL="mlx-community/Qwen3-32B-4bit"
DRAFT_MODEL="mlx-community/Qwen3-0.6B-4bit"

QUICK_PORT=8081
DEEP_PORT=8082

LOG_DIR="$PROJECT_DIR/mlx/logs"
mkdir -p "$LOG_DIR"

# Parse flags
SPECULATIVE=false
QUICK_ONLY=false
DEEP_ONLY=false

for arg in "$@"; do
    case "$arg" in
        --speculative) SPECULATIVE=true ;;
        --quick-only)  QUICK_ONLY=true ;;
        --deep-only)   DEEP_ONLY=true ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

# ── Helper: check if port is in use ────────────────────────────────────
port_in_use() {
    lsof -i :"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# ── Helper: wait for server to be ready ────────────────────────────────
wait_for_server() {
    local port=$1 name=$2 max_wait=120 elapsed=0
    echo -n "  Waiting for $name (port $port)..."
    while ! curl -s "http://localhost:$port/v1/models" >/dev/null 2>&1; do
        sleep 2
        elapsed=$((elapsed + 2))
        if [ $elapsed -ge $max_wait ]; then
            echo " TIMEOUT after ${max_wait}s!"
            echo "  Check logs: $LOG_DIR/${name}.log"
            return 1
        fi
        echo -n "."
    done
    echo " ready! (${elapsed}s)"
}

# ── Start Quick Model Server ───────────────────────────────────────────
start_quick() {
    if port_in_use $QUICK_PORT; then
        echo "⚠️  Port $QUICK_PORT already in use — quick server may already be running"
        return 0
    fi

    local cmd="$MLX_SERVER --model $QUICK_MODEL --port $QUICK_PORT --host 127.0.0.1 --log-level INFO"

    if [ "$SPECULATIVE" = true ]; then
        echo "🚀 Starting quick model (14B + 0.6B draft for speculative decoding)..."
        cmd="$cmd --draft-model $DRAFT_MODEL --num-draft-tokens 3"
    else
        echo "🚀 Starting quick model (14B)..."
    fi

    # HuggingFace needs proxy on Walmart VPN
    HTTP_PROXY=http://sysproxy.wal-mart.com:8080 \
    HTTPS_PROXY=http://sysproxy.wal-mart.com:8080 \
    nohup $cmd > "$LOG_DIR/quick.log" 2>&1 &
    echo $! > "$LOG_DIR/quick.pid"
    echo "  PID: $(cat "$LOG_DIR/quick.pid") → log: $LOG_DIR/quick.log"

    wait_for_server $QUICK_PORT "quick"
}

# ── Start Deep Model Server ───────────────────────────────────────────
start_deep() {
    if port_in_use $DEEP_PORT; then
        echo "⚠️  Port $DEEP_PORT already in use — deep server may already be running"
        return 0
    fi

    echo "🧠 Starting deep model (32B)..."
    local cmd="$MLX_SERVER --model $DEEP_MODEL --port $DEEP_PORT --host 127.0.0.1 --log-level INFO"

    HTTP_PROXY=http://sysproxy.wal-mart.com:8080 \
    HTTPS_PROXY=http://sysproxy.wal-mart.com:8080 \
    nohup $cmd > "$LOG_DIR/deep.log" 2>&1 &
    echo $! > "$LOG_DIR/deep.pid"
    echo "  PID: $(cat "$LOG_DIR/deep.pid") → log: $LOG_DIR/deep.log"

    wait_for_server $DEEP_PORT "deep"
}

# ── Main ───────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  MLX Server Launcher"
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ "$DEEP_ONLY" = true ]; then
    start_deep
elif [ "$QUICK_ONLY" = true ]; then
    start_quick
else
    start_quick
    echo ""
    start_deep
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ MLX servers running!"
echo ""
if [ "$DEEP_ONLY" != true ]; then
    echo "  Quick model: http://localhost:$QUICK_PORT/v1"
fi
if [ "$QUICK_ONLY" != true ]; then
    echo "  Deep model:  http://localhost:$DEEP_PORT/v1"
fi
echo ""
echo "  To use with the pipeline, set in config.toml:"
echo "    provider = \"mlx\""
echo "    quick_backend_url = \"http://localhost:$QUICK_PORT/v1\""
echo "    deep_backend_url  = \"http://localhost:$DEEP_PORT/v1\""
echo ""
echo "  Stop servers:  ./mlx/stop.sh"
echo "  View logs:     tail -f $LOG_DIR/quick.log"
echo "                 tail -f $LOG_DIR/deep.log"
echo "═══════════════════════════════════════════════════════════"
