#!/usr/bin/env bash
# OpenClaw Studio — paste this into any fresh Ubuntu server as root.
# Sets up: Docker · Ollama · LiteLLM proxy · Open WebUI · systemd auto-start
#
#   QWEN_MODEL=qwen2.5-coder:14b bash server.sh   # bigger model
# ---------------------------------------------------------------------------
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

QWEN_MODEL="${QWEN_MODEL:-qwen2.5-coder:7b}"
DIR="/opt/openclaw"
LOG="/var/log/openclaw.log"

exec > >(tee -a "$LOG") 2>&1

B='\033[1m'; C='\033[0;36m'; G='\033[0;32m'; R='\033[0;31m'; N='\033[0m'
log() { echo -e "${C}[$(date '+%H:%M:%S')]${N} $*"; }
ok()  { echo -e "${G}[OK]${N} $*"; }
die() { echo -e "${R}[ERR]${N} $*" >&2; exit 1; }

[[ "$EUID" -ne 0 ]] && die "Run as root: sudo bash server.sh"

echo -e "${B}── OpenClaw Studio server setup ──────────────────────────────${N}"
echo -e "   Model: ${C}${QWEN_MODEL}${N}   Log: $LOG"
echo -e "${B}──────────────────────────────────────────────────────────────${N}"

# ── Packages ────────────────────────────────────────────────────────────────
log "Updating packages..."
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq curl ufw ca-certificates gnupg lsb-release
ok "Packages ready."

# ── Firewall ────────────────────────────────────────────────────────────────
log "Configuring firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 3000/tcp comment "OpenClaw Studio"
ufw allow 4000/tcp comment "LiteLLM proxy"
ufw allow 11434/tcp comment "Ollama API"
ufw --force enable
ok "UFW active."

# ── Docker ──────────────────────────────────────────────────────────────────
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

# ── NVIDIA (optional) ───────────────────────────────────────────────────────
HAS_GPU=false
if lspci 2>/dev/null | grep -qi nvidia; then
  HAS_GPU=true
  log "NVIDIA GPU detected — installing container toolkit..."
  dist=$(. /etc/os-release; echo "$ID$VERSION_ID")
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -sL "https://nvidia.github.io/libnvidia-container/$dist/libnvidia-container.list" \
    | sed 's|deb https://|deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://|g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq
  apt-get install -y -qq nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
  ok "NVIDIA toolkit installed."
else
  log "No GPU — CPU-only mode."
fi

# ── Config files ─────────────────────────────────────────────────────────────
log "Writing config to $DIR..."
mkdir -p "$DIR"

# Build GPU block conditionally
GPU_SECTION=""
$HAS_GPU && GPU_SECTION='    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]'

cat > "$DIR/docker-compose.yml" <<COMPOSE
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
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
${GPU_SECTION}
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
      sh -c "OLLAMA_HOST=http://ollama:11434 ollama pull ${QWEN_MODEL} && echo done"
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
      - "4000:4000"
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
      - "3000:8080"
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

cat > "$DIR/litellm_config.yaml" <<YAML
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

echo "QWEN_MODEL=${QWEN_MODEL}" > "$DIR/.env"
ok "Config files written."

# ── Systemd ──────────────────────────────────────────────────────────────────
cat > /etc/systemd/system/openclaw-studio.service <<UNIT
[Unit]
Description=OpenClaw Studio (Ollama + LiteLLM + Open WebUI)
After=docker.service network-online.target
Requires=docker.service
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${DIR}
EnvironmentFile=${DIR}/.env
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
ok "Systemd service enabled (auto-starts on reboot)."

# ── Launch ───────────────────────────────────────────────────────────────────
log "Pulling images and starting stack (model pull may take a few minutes)..."
cd "$DIR"
docker compose pull --quiet
docker compose up -d

log "Waiting for Open WebUI..."
for i in $(seq 1 60); do
  curl -sf http://localhost:3000 &>/dev/null && break
  sleep 3
done

IP=$(curl -sf --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 \
     2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo -e "${B}── OpenClaw Studio is live ────────────────────────────────────${N}"
echo -e "   Browser  → ${G}http://${IP}:3000${N}"
echo -e "   Proxy    → http://${IP}:4000"
echo -e "   Ollama   → http://${IP}:11434"
echo ""
echo -e "   ${B}Use from your laptop:${N}"
echo -e "   export ANTHROPIC_BASE_URL=http://${IP}:4000"
echo -e "   export ANTHROPIC_API_KEY=sk-local-free"
echo -e "   claude"
echo -e "${B}───────────────────────────────────────────────────────────────${N}"
