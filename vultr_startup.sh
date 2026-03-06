#!/usr/bin/env bash
# vultr_startup.sh — Vultr cloud-init / User Data script
#
# Paste the contents of this file into the "User Data" field when
# creating a Vultr instance (Server → Additional Features → User Data).
#
# Recommended Vultr plan:
#   Optimized Cloud Compute — 2 vCPU / 4 GB RAM (CPU-only, ~$24/mo)
#   or any GPU instance for faster inference.
#
# What this script does:
#   1. Hardens the server (UFW firewall)
#   2. Installs Docker + Docker Compose plugin
#   3. Installs NVIDIA container toolkit if a GPU is present
#   4. Clones this repo to /opt/openclaw
#   5. Installs & enables the systemd service (auto-start on reboot)
#   6. Starts OpenClaw Studio immediately
#
# After boot completes (≈5–10 min first run for model pull):
#   Open WebUI studio → http://<your-vultr-ip>:3000
#   LiteLLM proxy     → http://<your-vultr-ip>:4000
#   Ollama API        → http://<your-vultr-ip>:11434
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_URL="https://github.com/kaliyuga187/Polyback.git"
INSTALL_DIR="/opt/openclaw"
QWEN_MODEL="${QWEN_MODEL:-qwen2.5-coder:7b}"
LOG_FILE="/var/log/openclaw_startup.log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

exec > >(tee -a "$LOG_FILE") 2>&1
log "=== OpenClaw Studio — Vultr startup ==="

# ── 1. System update ─────────────────────────────────────────────────────────
log "Updating packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
  curl wget git ufw ca-certificates gnupg lsb-release unzip

# ── 2. Firewall ───────────────────────────────────────────────────────────────
log "Configuring UFW firewall..."
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 3000/tcp comment "OpenClaw Studio (Open WebUI)"
ufw allow 4000/tcp comment "LiteLLM proxy"
ufw allow 11434/tcp comment "Ollama API"
ufw --force enable
log "UFW enabled."

# ── 3. Docker ─────────────────────────────────────────────────────────────────
log "Installing Docker..."
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list

  apt-get update -qq
  apt-get install -y -qq \
    docker-ce docker-ce-cli containerd.io \
    docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  log "Docker installed: $(docker --version)"
else
  log "Docker already installed: $(docker --version)"
fi

# ── 4. NVIDIA container toolkit (skip if no GPU) ─────────────────────────────
if lspci 2>/dev/null | grep -qi nvidia; then
  log "NVIDIA GPU detected — installing container toolkit..."
  distribution=$(. /etc/os-release; echo "$ID$VERSION_ID")
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
    | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
    > /etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -qq
  apt-get install -y -qq nvidia-container-toolkit
  nvidia-ctk runtime configure --runtime=docker
  systemctl restart docker
  log "NVIDIA container toolkit installed."
else
  log "No NVIDIA GPU found — CPU-only mode."
  # Patch docker-compose to remove GPU reservations for CPU-only instances
fi

# ── 5. Clone repo ─────────────────────────────────────────────────────────────
log "Cloning repo → $INSTALL_DIR ..."
if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" pull origin main
else
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# If no GPU, remove the GPU block from docker-compose so it doesn't fail
if ! lspci 2>/dev/null | grep -qi nvidia; then
  log "Patching docker-compose for CPU-only (removing GPU reservations)..."
  python3 - <<'PYEOF'
import re, pathlib
p = pathlib.Path("/opt/openclaw/docker-compose.yml")
text = p.read_text()
# Remove deploy.resources block
text = re.sub(r'\s+deploy:\s+resources:.*?capabilities: \[gpu\]', '', text, flags=re.DOTALL)
p.write_text(text)
PYEOF
fi

# Export model choice for docker-compose
export QWEN_MODEL
echo "QWEN_MODEL=${QWEN_MODEL}" > "$INSTALL_DIR/.env"

# ── 6. Install & enable systemd service ───────────────────────────────────────
log "Installing openclaw-studio.service..."
# Patch WorkingDirectory to match install location
sed "s|/opt/openclaw|$INSTALL_DIR|g" \
  "$INSTALL_DIR/openclaw-studio.service" \
  > /etc/systemd/system/openclaw-studio.service

systemctl daemon-reload
systemctl enable openclaw-studio
log "Service enabled — will auto-start on reboot."

# ── 7. First launch ───────────────────────────────────────────────────────────
log "Starting OpenClaw Studio (first pull may take several minutes)..."
cd "$INSTALL_DIR"
docker compose pull
docker compose up -d

# Wait for Open WebUI to be reachable
log "Waiting for Open WebUI on port 3000..."
for i in $(seq 1 60); do
  if curl -sf http://localhost:3000 &>/dev/null; then
    log "Open WebUI is up!"
    break
  fi
  sleep 5
done

# ── Done ──────────────────────────────────────────────────────────────────────
SERVER_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 \
            || hostname -I | awk '{print $1}')

log ""
log "============================================================"
log " OpenClaw Studio is running!"
log ""
log "  Browser studio  → http://${SERVER_IP}:3000"
log "  LiteLLM proxy   → http://${SERVER_IP}:4000"
log "  Ollama API      → http://${SERVER_IP}:11434"
log ""
log "  For Claude Code on your laptop:"
log "    export ANTHROPIC_BASE_URL=http://${SERVER_IP}:4000"
log "    export ANTHROPIC_API_KEY=sk-local-free"
log "    claude"
log "============================================================"
