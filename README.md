# Polyback
Polymarket strategy reverse tool

---

## OpenClaw Studio — free local AI in one script

Run Claude Code against a locally-hosted **Qwen2.5-Coder** model at zero cost.
Everything — Ollama, LiteLLM proxy, Open WebUI studio, systemd auto-start — is
compiled into a single script: **`openclaw.sh`**

```
Qwen2.5-Coder (Ollama) ──► LiteLLM proxy :4000 ──► Claude Code
                      └──► Open WebUI :3000  (browser chat studio)
```

---

## Usage

### Local machine (no Docker, launches Claude Code)
```bash
./openclaw.sh           # auto-detects non-root → local mode
./openclaw.sh local     # explicit
```

### Vultr / server (Docker stack + systemd auto-start, run as root)
```bash
sudo ./openclaw.sh vultr
# — or paste into Vultr User Data for fully automated deploy —
```

### Custom model
```bash
QWEN_MODEL=qwen2.5-coder:14b ./openclaw.sh
```

---

## How it works

| Mode | Stack | Survives reboot |
|---|---|---|
| `local` | Ollama + LiteLLM native processes | no |
| `vultr` | Docker Compose (Ollama + LiteLLM + Open WebUI) + systemd | yes |

Both modes write a temporary LiteLLM config that maps every Claude model name
to the local Qwen instance, then set `ANTHROPIC_BASE_URL` so Claude Code never
contacts Anthropic's servers.

---

## Vultr deploy

1. Create **Ubuntu 22.04** instance (≥4 vCPU / 8 GB RAM recommended)
2. Paste `openclaw.sh` contents into **User Data** → Deploy
3. After ~5–10 min: open `http://<ip>:3000`
4. On your laptop:
```bash
export ANTHROPIC_BASE_URL=http://<ip>:4000
export ANTHROPIC_API_KEY=sk-local-free
claude
```

Ports opened automatically: `3000` (studio) · `4000` (proxy) · `11434` (Ollama)

---

## Model options

| Model | RAM needed | Quality |
|---|---|---|
| `qwen2.5-coder:7b` (default) | 5 GB | Good |
| `qwen2.5-coder:14b` | 10 GB | Better |
| `qwen2.5-coder:32b` | 22 GB | Best |

---

## Service management (Vultr)
```bash
systemctl status openclaw-studio
systemctl restart openclaw-studio
journalctl -u openclaw-studio -f
```
