#!/usr/bin/env bash
# run_local.sh — Start the full free-local-AI stack and launch Claude Code
#
# Stack:
#   Ollama (Qwen2.5-Coder) → LiteLLM proxy (port 4000) → Claude Code
#
# Usage:
#   ./run_local.sh              # start everything
#   ./run_local.sh --model qwen2.5-coder:14b   # use a larger model
set -euo pipefail

QWEN_MODEL="${1:-${QWEN_MODEL:-qwen2.5-coder:7b}}"
LITELLM_PORT=4000

cleanup() {
  echo ""
  echo "==> Stopping services..."
  [[ -n "${OLLAMA_PID:-}" ]] && kill "$OLLAMA_PID" 2>/dev/null || true
  [[ -n "${LITELLM_PID:-}" ]] && kill "$LITELLM_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── 1. Ollama ────────────────────────────────────────────────────────────────
echo "==> Checking Ollama..."
if ! command -v ollama &>/dev/null; then
  echo "    Ollama not found. Run ./setup_ollama.sh first."
  exit 1
fi

if ! pgrep -x ollama &>/dev/null; then
  echo "    Starting Ollama daemon..."
  ollama serve &>/tmp/ollama.log &
  OLLAMA_PID=$!
  sleep 2
else
  echo "    Ollama already running."
fi

# Ensure model is available
if ! ollama list | grep -q "${QWEN_MODEL%%:*}"; then
  echo "==> Pulling $QWEN_MODEL (first time only)..."
  ollama pull "$QWEN_MODEL"
fi

# ── 2. LiteLLM proxy ─────────────────────────────────────────────────────────
echo "==> Checking LiteLLM..."
if ! python3 -c "import litellm" &>/dev/null; then
  echo "    Installing litellm[proxy]..."
  pip3 install --quiet "litellm[proxy]"
fi

echo "==> Starting LiteLLM proxy on port $LITELLM_PORT..."
litellm --config litellm_config.yaml --port "$LITELLM_PORT" &>/tmp/litellm.log &
LITELLM_PID=$!

# Wait for proxy to be ready
echo "    Waiting for proxy..."
for i in $(seq 1 30); do
  if curl -sf "http://localhost:$LITELLM_PORT/health" &>/dev/null; then
    echo "    Proxy ready."
    break
  fi
  sleep 1
done

# ── 3. Claude Code ───────────────────────────────────────────────────────────
echo ""
echo "==> Launching Claude Code with local Qwen ($QWEN_MODEL)..."
echo "    ANTHROPIC_BASE_URL=http://localhost:$LITELLM_PORT"
echo "    ANTHROPIC_API_KEY=sk-local-free (no cost)"
echo ""

# shellcheck source=.env.local
source "$(dirname "$0")/.env.local"
exec claude
