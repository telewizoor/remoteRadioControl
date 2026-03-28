#!/bin/bash
# install.sh — Remote Radio Control server installer
# Tested on: Raspberry Pi 4, Debian Bookworm
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'
CYN='\033[0;36m'; BLD='\033[1m';   RST='\033[0m'
info()  { echo -e "${CYN}[INFO]${RST} $*"; }
ok()    { echo -e "${GRN}[ OK ]${RST} $*"; }
warn()  { echo -e "${YEL}[WARN]${RST} $*"; }
err()   { echo -e "${RED}[ERR ]${RST} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_DIR="$(dirname "$REPO_DIR")"
LOG_FILE="$SCRIPT_DIR/install.log"

echo "" | tee "$LOG_FILE"
echo -e "${BLD}=== Remote Radio Control — installation ===${RST}" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# ─────────────────────────────────────────────────────────────
# 1. System packages
# ─────────────────────────────────────────────────────────────
info "Installing system packages..."
sudo apt-get update -qq 2>&1 | tee -a "$LOG_FILE"
sudo apt-get install -y \
    nodejs npm ffmpeg \
    build-essential automake libtool git \
    python3 python3-venv python3-pip \
    mumble-server \
    2>&1 | tee -a "$LOG_FILE"
ok "System packages installed"

# ─────────────────────────────────────────────────────────────
# 2. ZeroTier
# ─────────────────────────────────────────────────────────────
if command -v zerotier-cli &>/dev/null; then
    ok "ZeroTier already installed ($(zerotier-cli -v 2>/dev/null))"
else
    info "Installing ZeroTier..."
    curl -s https://install.zerotier.com | sudo bash 2>&1 | tee -a "$LOG_FILE"
    sudo systemctl enable zerotier-one
    sudo systemctl start zerotier-one
    ok "ZeroTier installed & started"
fi

# ─────────────────────────────────────────────────────────────
# 3. OpenWebRX+ (optional — uncomment to enable)
# ─────────────────────────────────────────────────────────────
info "Installing OpenWebRX+..."
curl -s https://luarvique.github.io/ppa/openwebrx-plus.gpg \
    | sudo gpg --yes --dearmor -o /etc/apt/trusted.gpg.d/openwebrx-plus.gpg
sudo tee /etc/apt/sources.list.d/openwebrx-plus.list \
    <<<"deb [signed-by=/etc/apt/trusted.gpg.d/openwebrx-plus.gpg] https://luarvique.github.io/ppa/bookworm ./"
sudo apt-get update -qq && sudo apt-get install -y openwebrx

# ─────────────────────────────────────────────────────────────
# 4. Hamlib (build from source)
# ─────────────────────────────────────────────────────────────
if command -v rigctld &>/dev/null; then
    ok "Hamlib already installed ($(rigctld --version 2>&1 | head -1))"
else
    info "Building Hamlib from source..."
    cd "$PROJECT_DIR"
    if [ -d Hamlib ]; then
        cd Hamlib && git pull
    else
        git clone https://github.com/Hamlib/Hamlib.git
        cd Hamlib
    fi
    ./bootstrap 2>&1 | tee -a "$LOG_FILE"
    ./configure 2>&1 | tee -a "$LOG_FILE"
    make -j"$(nproc)" 2>&1 | tee -a "$LOG_FILE"
    sudo make install 2>&1 | tee -a "$LOG_FILE"
    sudo ldconfig
    ok "Hamlib installed"
fi

# ─────────────────────────────────────────────────────────────
# 5. Node.js dependencies
# ─────────────────────────────────────────────────────────────
info "Installing Node.js dependencies..."
cd "$REPO_DIR/remoteControlNode"
npm install 2>&1 | tee -a "$LOG_FILE"
ok "Node.js dependencies installed"

# ─────────────────────────────────────────────────────────────
# 6. Python virtual environment
# ─────────────────────────────────────────────────────────────
info "Setting up Python environment..."
cd "$REPO_DIR"
if [ ! -d env ]; then
    python3 -m venv env
fi
source env/bin/activate
pip install -r requirements.txt 2>&1 | tee -a "$LOG_FILE"
ok "Python environment ready"

# ─────────────────────────────────────────────────────────────
# 7. SSL certificates (for HTTPS Node server)
# ─────────────────────────────────────────────────────────────
cd "$REPO_DIR/remoteControlNode"
if [ ! -f key.pem ] || [ ! -f cert.pem ]; then
    info "Generating self-signed SSL certificates..."
    openssl req -x509 -newkey rsa:2048 \
        -keyout key.pem -out cert.pem \
        -days 3650 -nodes \
        -subj '/CN=remoteRadioControl' 2>&1 | tee -a "$LOG_FILE"
    ok "SSL certificates generated"
else
    ok "SSL certificates already exist"
fi

# ─────────────────────────────────────────────────────────────
# 8. Mumble server
# ─────────────────────────────────────────────────────────────
info "Enabling Mumble server..."
sudo systemctl enable mumble-server
sudo systemctl start mumble-server
ok "mumble-server — enabled & started"

# ─────────────────────────────────────────────────────────────
# 9. Configuration (interactive)
# ─────────────────────────────────────────────────────────────
echo ""
echo -e "${BLD}── Installation complete — starting configuration ──${RST}"
echo ""
bash "$SCRIPT_DIR/configure.sh"