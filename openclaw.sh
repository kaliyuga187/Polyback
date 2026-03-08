#!/usr/bin/env bash
# openclaw.sh — OpenClaw Studio: single-script installer + launcher
#
# Modes (auto-detected):
#   local   — installs Ollama + LiteLLM on this machine, launches Claude Code
#   vultr   — full server setup: Docker stack + systemd auto-start (run as root)
#
# Usage:
#   ./openclaw.sh                          # auto-detect mode
#   ./openclaw.sh local                    # force local mode
#   ./openclaw.sh vultr                    # force Vultr/server mode
#   QWEN_MODEL=qwen2.5-coder:14b ./openclaw.sh
# ---------------------------------------------------------------------------
set -euo pipefail

QWEN_MODEL="${QWEN_MODEL:-qwen2.5-coder:7b}"
LITELLM_PORT=4000
OLLAMA_PORT=11434
STUDIO_PORT=3000
INSTALL_DIR="/opt/openclaw"
REPO_URL="https://github.com/kaliyuga187/Polyback.git"
LOG_FILE="/tmp/openclaw.log"

# ── Helpers ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
log()  { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*" | tee -a "$LOG_FILE"; }
die()  { echo -e "${RED}[ERR]${NC} $*" >&2; exit 1; }
hr()   { echo -e "${BOLD}────────────────────────────────────────────${NC}"; }

wait_for() {
  local url="$1" label="$2" tries="${3:-30}"
  log "Waiting for $label..."
  for i in $(seq 1 "$tries"); do
    if curl -sf "$url" &>/dev/null; then ok "$label is up."; return 0; fi
    sleep 2
  done
  die "$label did not start in time. Check $LOG_FILE"
}

# ── Mode detection ────────────────────────────────────────────────────────────
MODE="${1:-}"
if [[ -z "$MODE" ]]; then
  [[ "$EUID" -eq 0 ]] && MODE="vultr" || MODE="local"
fi

hr
echo -e "${BOLD}  OpenClaw Studio — free local AI (Qwen + Claude Code)${NC}"
echo -e "  Mode: ${CYAN}${MODE}${NC}  |  Model: ${CYAN}${QWEN_MODEL}${NC}"
hr

# ═══════════════════════════════════════════════════════════════════════════════
# LOCAL MODE — Ollama + LiteLLM natively, no Docker, launches Claude Code
# ═══════════════════════════════════════════════════════════════════════════════
if [[ "$MODE" == "local" ]]; then

  cleanup() {
    log "Shutting down..."
    [[ -n "${OLLAMA_PID:-}" ]] && kill "$OLLAMA_PID" 2>/dev/null || true
    [[ -n "${LITELLM_PID:-}" ]] && kill "$LITELLM_PID" 2>/dev/null || true
  }
  trap cleanup EXIT INT TERM

  # ── Ollama ──────────────────────────────────────────────────────────────────
  log "Checking Ollama..."
  if ! command -v ollama &>/dev/null; then
    log "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  ok "Ollama: $(ollama --version)"

  if ! pgrep -x ollama &>/dev/null; then
    log "Starting Ollama daemon..."
    ollama serve >>"$LOG_FILE" 2>&1 &
    OLLAMA_PID=$!
    wait_for "http://localhost:${OLLAMA_PORT}/api/tags" "Ollama"
  else
    ok "Ollama already running."
  fi

  if ! ollama list 2>/dev/null | grep -q "${QWEN_MODEL%%:*}"; then
    log "Pulling ${QWEN_MODEL} (first time only)..."
    ollama pull "$QWEN_MODEL"
  fi
  ok "Model ready: $QWEN_MODEL"

  # ── LiteLLM config (written inline — no external file needed) ───────────────
  LITELLM_CFG="$(mktemp /tmp/openclaw_litellm_XXXX.yaml)"
  cat > "$LITELLM_CFG" <<YAML
model_list:
  - model_name: claude-3-5-sonnet-20241022
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://localhost:${OLLAMA_PORT}
  - model_name: claude-opus-4-6
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://localhost:${OLLAMA_PORT}
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://localhost:${OLLAMA_PORT}
  - model_name: claude-haiku-4-5-20251001
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://localhost:${OLLAMA_PORT}
litellm_settings:
  drop_params: true
  num_retries: 3
  request_timeout: 600
general_settings:
  master_key: "sk-local-free"
  port: ${LITELLM_PORT}
YAML

  log "Checking LiteLLM..."
  if ! python3 -c "import litellm" &>/dev/null; then
    log "Installing litellm[proxy]..."
    pip3 install --quiet "litellm[proxy]"
  fi
  ok "LiteLLM ready."

  log "Starting LiteLLM proxy on :${LITELLM_PORT}..."
  litellm --config "$LITELLM_CFG" --port "$LITELLM_PORT" >>"$LOG_FILE" 2>&1 &
  LITELLM_PID=$!
  wait_for "http://localhost:${LITELLM_PORT}/health" "LiteLLM proxy"

  # ── Launch Claude Code ───────────────────────────────────────────────────────
  hr
  log "Launching Claude Code → local Qwen (${QWEN_MODEL}) — no API cost"
  log "  Proxy : http://localhost:${LITELLM_PORT}"
  log "  Key   : sk-local-free"
  hr

  export ANTHROPIC_BASE_URL="http://localhost:${LITELLM_PORT}"
  export ANTHROPIC_API_KEY="sk-local-free"
  export CLAUDE_CODE_DISABLE_TELEMETRY=1
  exec claude

# ═══════════════════════════════════════════════════════════════════════════════
# VULTR / SERVER MODE — Docker stack + systemd, survives reboots
# ═══════════════════════════════════════════════════════════════════════════════
elif [[ "$MODE" == "vultr" ]]; then

  [[ "$EUID" -ne 0 ]] && die "Vultr mode must be run as root (sudo $0 vultr)"
  LOG_FILE="/var/log/openclaw_startup.log"
  exec > >(tee -a "$LOG_FILE") 2>&1

  # ── System deps ─────────────────────────────────────────────────────────────
  log "Updating packages..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get upgrade -y -qq
  apt-get install -y -qq curl wget git ufw ca-certificates gnupg lsb-release python3

  # ── Firewall ─────────────────────────────────────────────────────────────────
  log "Configuring UFW..."
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow ssh
  ufw allow "${STUDIO_PORT}/tcp" comment "OpenClaw Studio"
  ufw allow "${LITELLM_PORT}/tcp" comment "LiteLLM proxy"
  ufw allow "${OLLAMA_PORT}/tcp" comment "Ollama API"
  ufw --force enable
  ok "Firewall configured."

  # ── Docker ───────────────────────────────────────────────────────────────────
  if ! command -v docker &>/dev/null; then
    log "Installing Docker..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
      > /etc/apt/sources.list.d/docker.list
    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
      docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    ok "Docker installed."
  else
    ok "Docker already present."
  fi

  # ── NVIDIA toolkit (if GPU found) ────────────────────────────────────────────
  HAS_GPU=false
  if lspci 2>/dev/null | grep -qi nvidia; then
    HAS_GPU=true
    log "NVIDIA GPU detected — installing container toolkit..."
    distribution=$(. /etc/os-release; echo "$ID$VERSION_ID")
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -sL "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -qq
    apt-get install -y -qq nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
    ok "NVIDIA toolkit installed."
  else
    log "No GPU found — CPU-only mode."
  fi

  # ── Write config files inline (no repo clone needed) ─────────────────────────
  log "Writing config to ${INSTALL_DIR}..."
  mkdir -p "$INSTALL_DIR"

  # docker-compose.yml
  GPU_BLOCK=""
  if $HAS_GPU; then
    GPU_BLOCK='    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]'
  fi

  cat > "${INSTALL_DIR}/docker-compose.yml" <<COMPOSE
version: "3.9"

volumes:
  ollama_data:
  openwebui_data:

services:
  ollama:
    image: ollama/ollama:latest
    container_name: openclaw_ollama
    restart: unless-stopped
    ports:
      - "${OLLAMA_PORT}:11434"
    volumes:
      - ollama_data:/root/.ollama
${GPU_BLOCK}
    environment:
      - OLLAMA_KEEP_ALIVE=24h
      - OLLAMA_NUM_PARALLEL=2
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:11434/api/tags"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama_init:
    image: ollama/ollama:latest
    container_name: openclaw_init
    depends_on:
      ollama:
        condition: service_healthy
    restart: "no"
    entrypoint: >
      sh -c "OLLAMA_HOST=http://ollama:11434 ollama pull \${QWEN_MODEL:-${QWEN_MODEL}} && echo done"
    volumes:
      - ollama_data:/root/.ollama

  litellm:
    image: ghcr.io/berriai/litellm:main-latest
    container_name: openclaw_litellm
    restart: unless-stopped
    depends_on:
      ollama:
        condition: service_healthy
    ports:
      - "${LITELLM_PORT}:4000"
    volumes:
      - ./litellm_config.yaml:/app/config.yaml:ro
    command: ["--config", "/app/config.yaml", "--port", "4000", "--host", "0.0.0.0"]
    environment:
      - LITELLM_MASTER_KEY=sk-local-free
      - OLLAMA_API_BASE=http://ollama:11434
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:4000/health"]
      interval: 15s
      timeout: 5s
      retries: 5

  openwebui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: openclaw_studio
    restart: unless-stopped
    depends_on:
      - ollama
      - litellm
    ports:
      - "${STUDIO_PORT}:8080"
    volumes:
      - openwebui_data:/app/backend/data
    environment:
      - OLLAMA_BASE_URL=http://ollama:11434
      - OPENAI_API_BASE_URL=http://litellm:4000/v1
      - OPENAI_API_KEY=sk-local-free
      - WEBUI_NAME=OpenClaw Studio
      - WEBUI_AUTH=false
      - DEFAULT_MODELS=${QWEN_MODEL}
    extra_hosts:
      - "host.docker.internal:host-gateway"
COMPOSE

  # litellm_config.yaml
  cat > "${INSTALL_DIR}/litellm_config.yaml" <<YAML
model_list:
  - model_name: claude-3-5-sonnet-20241022
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://ollama:11434
  - model_name: claude-opus-4-6
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://ollama:11434
  - model_name: claude-sonnet-4-6
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://ollama:11434
  - model_name: claude-haiku-4-5-20251001
    litellm_params:
      model: ollama/${QWEN_MODEL}
      api_base: http://ollama:11434
litellm_settings:
  drop_params: true
  num_retries: 3
  request_timeout: 600
general_settings:
  master_key: "sk-local-free"
  port: 4000
YAML

  echo "QWEN_MODEL=${QWEN_MODEL}" > "${INSTALL_DIR}/.env"
  ok "Config files written."

  # ── Systemd service ──────────────────────────────────────────────────────────
  cat > /etc/systemd/system/openclaw-studio.service <<UNIT
[Unit]
Description=OpenClaw Studio (Ollama + LiteLLM + Open WebUI)
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${INSTALL_DIR}/.env
ExecStartPre=/usr/bin/docker compose pull --quiet
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
Restart=on-failure
RestartSec=30s
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable openclaw-studio
  ok "Systemd service installed and enabled (auto-starts on reboot)."

  # ── First launch ─────────────────────────────────────────────────────────────
  log "Starting OpenClaw Studio (model pull may take a few minutes)..."
  cd "$INSTALL_DIR"
  docker compose pull
  docker compose up -d

  wait_for "http://localhost:${STUDIO_PORT}" "Open WebUI" 60

  SERVER_IP=$(curl -sf --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 \
              2>/dev/null || hostname -I | awk '{print $1}')

  hr
  ok "OpenClaw Studio is live!"
  echo ""
  echo -e "  ${BOLD}Browser studio${NC}  → http://${SERVER_IP}:${STUDIO_PORT}"
  echo -e "  ${BOLD}LiteLLM proxy${NC}   → http://${SERVER_IP}:${LITELLM_PORT}"
  echo -e "  ${BOLD}Ollama API${NC}      → http://${SERVER_IP}:${OLLAMA_PORT}"
  echo ""
  echo -e "  ${BOLD}Use Claude Code from your laptop:${NC}"
  echo -e "    export ANTHROPIC_BASE_URL=http://${SERVER_IP}:${LITELLM_PORT}"
  echo -e "    export ANTHROPIC_API_KEY=sk-local-free"
  echo -e "    claude"
  hr

else
  die "Unknown mode '${MODE}'. Use: $0 [local|vultr]"
fi
