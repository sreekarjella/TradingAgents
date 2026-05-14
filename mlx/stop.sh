#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# MLX Server Stopper — gracefully shuts down quick & deep model servers
#
# Usage:
#   ./mlx/stop.sh              # Stop all MLX servers
#   ./mlx/stop.sh --quick      # Stop only quick model server
#   ./mlx/stop.sh --deep       # Stop only deep model server
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

stop_server() {
    local name=$1
    local pidfile="$LOG_DIR/${name}.pid"

    if [ ! -f "$pidfile" ]; then
        echo "  No PID file for $name server"
        return 0
    fi

    local pid
    pid=$(cat "$pidfile")

    if kill -0 "$pid" 2>/dev/null; then
        echo "  Stopping $name server (PID $pid)..."
        kill "$pid"
        # Wait up to 10s for graceful shutdown
        local waited=0
        while kill -0 "$pid" 2>/dev/null && [ $waited -lt 10 ]; do
            sleep 1
            waited=$((waited + 1))
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Force-killing $name server..."
            kill -9 "$pid" 2>/dev/null || true
        fi
        echo "  ✅ $name server stopped"
    else
        echo "  $name server already stopped (PID $pid not running)"
    fi

    rm -f "$pidfile"
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  MLX Server Shutdown"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Parse flags
STOP_QUICK=true
STOP_DEEP=true

for arg in "$@"; do
    case "$arg" in
        --quick) STOP_DEEP=false ;;
        --deep)  STOP_QUICK=false ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

[ "$STOP_QUICK" = true ] && stop_server "quick"
[ "$STOP_DEEP" = true ] && stop_server "deep"

echo ""
echo "  Done!"
echo "═══════════════════════════════════════════════════════════"
