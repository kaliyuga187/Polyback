#!/usr/bin/env bash
# setup_ollama.sh — Install Ollama and pull Qwen for free local AI
set -euo pipefail

QWEN_MODEL="${QWEN_MODEL:-qwen2.5-coder:7b}"

echo "==> Installing Ollama..."
if ! command -v ollama &>/dev/null; then
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "    Ollama already installed: $(ollama --version)"
fi

echo "==> Starting Ollama daemon (background)..."
ollama serve &>/tmp/ollama.log &
OLLAMA_PID=$!
echo "    PID: $OLLAMA_PID"

# Wait for Ollama to be ready
echo "==> Waiting for Ollama API..."
for i in $(seq 1 20); do
  if curl -sf http://localhost:11434/api/tags &>/dev/null; then
    echo "    Ready."
    break
  fi
  sleep 1
done

echo "==> Pulling model: $QWEN_MODEL"
ollama pull "$QWEN_MODEL"

echo ""
echo "==> Done! Model '$QWEN_MODEL' is ready."
echo "    Ollama API: http://localhost:11434"
echo "    To run the full Claude Code proxy stack, run: ./run_local.sh"
