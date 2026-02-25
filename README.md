# Polyback
Polymarket strategy reverse tool

---

## Run Claude Code free & locally with Qwen

This repo includes a zero-cost local AI stack:

```
Ollama (Qwen2.5-Coder) ──► LiteLLM proxy :4000 ──► Claude Code
```

### Quick start

```bash
# 1. Install Ollama + pull the Qwen model (one-time)
./setup_ollama.sh

# 2. Start everything and open Claude Code
./run_local.sh
```

### Model options

| Model | VRAM | Quality |
|---|---|---|
| `qwen2.5-coder:7b` (default) | ~5 GB | Good |
| `qwen2.5-coder:14b` | ~10 GB | Better |
| `qwen2.5-coder:32b` | ~22 GB | Best |

```bash
# Use a larger model
QWEN_MODEL=qwen2.5-coder:14b ./run_local.sh
```

### How it works

- **Ollama** runs the Qwen model locally on your hardware (CPU or GPU).
- **LiteLLM** (`litellm_config.yaml`) acts as a drop-in proxy that translates
  Anthropic-format API calls from Claude Code into Ollama-compatible requests.
- **`.env.local`** points `ANTHROPIC_BASE_URL` at the proxy and sets a dummy
  API key so Claude Code never contacts Anthropic's servers.

### Manual environment setup

If you want to wire things up yourself without `run_local.sh`:

```bash
# Terminal 1 — Ollama
ollama serve

# Terminal 2 — LiteLLM proxy
pip install "litellm[proxy]"
litellm --config litellm_config.yaml --port 4000

# Terminal 3 — Claude Code
source .env.local
claude
```
