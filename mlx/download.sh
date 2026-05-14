#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────
# MLX Model Downloader — pre-downloads all models from HuggingFace
#
# Downloads through Walmart proxy. Run this BEFORE start.sh to avoid
# blocking on first startup.
#
# Models:
#   - Qwen3-14B-4bit  (~9 GB)   → quick thinker
#   - Qwen3-32B-4bit  (~20 GB)  → deep thinker
#   - Qwen3-0.6B-4bit (~0.4 GB) → speculative decoding draft
#
# Usage:
#   ./mlx/download.sh              # Download all models
#   ./mlx/download.sh --quick      # Download quick model only
#   ./mlx/download.sh --deep       # Download deep model only
#   ./mlx/download.sh --draft      # Download draft model only
# ─────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON="$PROJECT_DIR/.venv/bin/python3"

# Models to download
QUICK_MODEL="mlx-community/Qwen3-14B-4bit"
DEEP_MODEL="mlx-community/Qwen3-32B-4bit"
DRAFT_MODEL="mlx-community/Qwen3-0.6B-4bit"

# Set proxy for HuggingFace access on Walmart VPN
export HTTP_PROXY=http://sysproxy.wal-mart.com:8080
export HTTPS_PROXY=http://sysproxy.wal-mart.com:8080

# Parse flags
DOWNLOAD_QUICK=true
DOWNLOAD_DEEP=true
DOWNLOAD_DRAFT=true

for arg in "$@"; do
    case "$arg" in
        --quick) DOWNLOAD_DEEP=false; DOWNLOAD_DRAFT=false ;;
        --deep)  DOWNLOAD_QUICK=false; DOWNLOAD_DRAFT=false ;;
        --draft) DOWNLOAD_QUICK=false; DOWNLOAD_DEEP=false ;;
        *) echo "Unknown flag: $arg"; exit 1 ;;
    esac
done

download_model() {
    local model=$1 desc=$2
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  📥 Downloading: $desc"
    echo "     Model: $model"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    $PYTHON -c "
from huggingface_hub import snapshot_download
import os
os.environ['HTTP_PROXY'] = 'http://sysproxy.wal-mart.com:8080'
os.environ['HTTPS_PROXY'] = 'http://sysproxy.wal-mart.com:8080'
path = snapshot_download('$model')
print(f'  ✅ Downloaded to: {path}')
"
    echo "  ✅ $desc — done!"
}

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  MLX Model Downloader"
echo "  Proxy: $HTTPS_PROXY"
echo "═══════════════════════════════════════════════════════════"

if [ "$DOWNLOAD_DRAFT" = true ]; then
    download_model "$DRAFT_MODEL" "Draft model (0.6B) — speculative decoding"
fi

if [ "$DOWNLOAD_QUICK" = true ]; then
    download_model "$QUICK_MODEL" "Quick model (14B) — analysts & debate"
fi

if [ "$DOWNLOAD_DEEP" = true ]; then
    download_model "$DEEP_MODEL" "Deep model (32B) — research & portfolio mgr"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  ✅ All downloads complete!"
echo ""
echo "  Next: ./mlx/start.sh"
echo "═══════════════════════════════════════════════════════════"
