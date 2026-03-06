# Polyback
Polymarket strategy reverse tool

---

## OpenClaw Studio — free local AI, deployable on Vultr

Run Claude Code (or any Anthropic-API client) against a locally-hosted
**Qwen2.5-Coder** model at zero per-token cost. Includes a full browser
chat studio (Open WebUI) and one-command Vultr cloud deployment.

```
┌──────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│  Claude Code │───►│  LiteLLM proxy :4000│───►│  Ollama :11434   │
│  (your box)  │    │  (Anthropic ↔ OAI)  │    │  Qwen2.5-Coder   │
└──────────────┘    └─────────────────────┘    └──────────────────┘
                                                        │
┌──────────────┐                                        │
│ Open WebUI   │◄───────────────────────────────────────┘
│ studio :3000 │   (browser chat, model management)
└──────────────┘
```

---

## Option A — Run locally (your own machine)

```bash
# 1. Install Ollama + pull Qwen (one-time)
./setup_ollama.sh

# 2. Start full Docker stack (studio + proxy)
docker compose up -d

# 3. Open browser studio
open http://localhost:3000

# 4. Point Claude Code at local proxy
source .env.local && claude
```

---

## Option B — Deploy on Vultr (auto-start on boot)

### Recommended instance

| | |
|---|---|
| Plan | **Optimized Cloud Compute** |
| CPU | 4 vCPU / 8 GB RAM (CPU) — or any GPU instance |
| OS | Ubuntu 22.04 LTS x64 |
| Cost | ~$48/mo CPU · GPU pricing varies |

### Step 1 — Create Vultr instance with User Data

1. Go to **Vultr → Deploy New Server**
2. Choose OS: **Ubuntu 22.04**
3. Scroll to **Additional Features → User Data**
4. Paste the entire contents of `vultr_startup.sh` into the field
5. Deploy

The script runs automatically on first boot and:
- Configures UFW firewall (ports 3000, 4000, 11434)
- Installs Docker + NVIDIA toolkit (if GPU present)
- Clones this repo to `/opt/openclaw`
- Installs & enables `openclaw-studio.service` (survives reboots)
- Pulls the Qwen model and starts all services

### Step 2 — Access your studio (~5–10 min after deploy)

```
http://<vultr-ip>:3000   → Open WebUI (browser chat)
http://<vultr-ip>:4000   → LiteLLM proxy (for Claude Code)
http://<vultr-ip>:11434  → Ollama raw API
```

### Step 3 — Point Claude Code on your laptop at the server

```bash
export ANTHROPIC_BASE_URL=http://<vultr-ip>:4000
export ANTHROPIC_API_KEY=sk-local-free
claude
```

Or add to your shell profile to make it permanent:

```bash
echo 'export ANTHROPIC_BASE_URL=http://<vultr-ip>:4000' >> ~/.zshrc
echo 'export ANTHROPIC_API_KEY=sk-local-free'           >> ~/.zshrc
```

---

## Model options

| Model | VRAM / RAM | Quality |
|---|---|---|
| `qwen2.5-coder:7b` (default) | 5 GB | Good |
| `qwen2.5-coder:14b` | 10 GB | Better |
| `qwen2.5-coder:32b` | 22 GB | Best |

Change model before deploying:

```bash
# In User Data or on the server:
QWEN_MODEL=qwen2.5-coder:14b ./vultr_startup.sh
```

Or on a running server:

```bash
cd /opt/openclaw
QWEN_MODEL=qwen2.5-coder:14b docker compose up -d
```

---

## Service management (on Vultr server)

```bash
# Status
systemctl status openclaw-studio

# Restart
systemctl restart openclaw-studio

# View logs
journalctl -u openclaw-studio -f

# Stop
systemctl stop openclaw-studio
```

---

## File reference

| File | Purpose |
|---|---|
| `docker-compose.yml` | Ollama + LiteLLM + Open WebUI stack |
| `litellm_config.yaml` | Maps Claude model names → Ollama |
| `openclaw-studio.service` | Systemd unit (auto-start on boot) |
| `vultr_startup.sh` | Vultr User Data / cloud-init script |
| `setup_ollama.sh` | Local Ollama install helper |
| `run_local.sh` | Local single-command launcher |
| `.env.local` | Env vars for Claude Code → local proxy |
