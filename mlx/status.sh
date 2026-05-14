#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# MLX Download Status — check progress of all model downloads
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

HF_CACHE="$HOME/.cache/huggingface/hub"

check_model() {
    local repo=$1 desc=$2 expected_gb=$3
    local safe_name
    safe_name=$(echo "$repo" | sed 's/\//-/g')
    local dir="$HF_CACHE/models--${safe_name}"

    if [ ! -d "$dir" ]; then
        echo "  ⬜ $desc ($repo) — not started"
        return
    fi

    # Count incomplete files
    local incomplete
    incomplete=$(find "$dir" -name "*.incomplete" 2>/dev/null | wc -l | tr -d ' ')

    # Calculate current size
    local size_bytes
    size_bytes=$(du -s "$dir" 2>/dev/null | awk '{print $1}')
    local size_gb
    size_gb=$(echo "scale=2; $size_bytes / 1048576" | bc 2>/dev/null || echo "?")

    if [ "$incomplete" -gt 0 ]; then
        echo "  🔄 $desc — ${size_gb} GB / ~${expected_gb} GB (${incomplete} files still downloading)"
    else
        # Check if snapshot exists (= download complete)
        if [ -d "$dir/snapshots" ] && [ "$(ls -A "$dir/snapshots/" 2>/dev/null)" ]; then
            echo "  ✅ $desc — ${size_gb} GB (complete!)"
        else
            echo "  ⚠️  $desc — ${size_gb} GB (may be incomplete)"
        fi
    fi
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  MLX Model Download Status"
echo "═══════════════════════════════════════════════════════════"
echo ""
check_model "mlx-community/Qwen3-0.6B-4bit" "Draft  (0.6B)" "0.4"
check_model "mlx-community/Qwen3-14B-4bit" "Quick  (14B)" "9.3"
check_model "mlx-community/Qwen3-32B-4bit" "Deep   (32B)" "20"
echo ""

# Check for running download processes
running=$(ps aux | grep -c "[s]napshot_download" || true)
if [ "$running" -gt 0 ]; then
    echo "  📡 $running download process(es) still running"
else
    echo "  🏁 No active downloads"
fi
echo "═══════════════════════════════════════════════════════════"
