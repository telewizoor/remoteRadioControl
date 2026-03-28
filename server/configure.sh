#!/bin/bash
# configure.sh — interactive configuration for remoteRadioControl
# Updates settings in startHamlib.sh and installs .service files

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HAMLIB_SH="$SCRIPT_DIR/startHamlib.sh"
SERVICE_FILES=("$SCRIPT_DIR"/*.service)

# ── Colors ────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YEL='\033[1;33m'
CYN='\033[0;36m'
BLD='\033[1m'
RST='\033[0m'

info()    { echo -e "${CYN}[INFO]${RST} $*"; }
ok()      { echo -e "${GRN}[ OK ]${RST} $*"; }
warn()    { echo -e "${YEL}[WARN]${RST} $*"; }
changed() { echo -e "${GRN}  ✔ $*${RST}"; }
skip()    { echo -e "  – $* (no change)"; }

ask() {
    # ask "Question" "default_value" → result in $REPLY
    local prompt="$1" default="$2"
    echo -en "${BLD}${prompt}${RST} [${YEL}${default}${RST}]: "
    read -r input
    REPLY="${input:-$default}"
}

# ── Read current values from startHamlib.sh ───────────────────
cur_rig=$(  grep -oP '^RIG=\K.*'  "$HAMLIB_SH" || echo "?")
cur_baud=$( grep -oP '^BAUD=\K.*' "$HAMLIB_SH" || echo "?")
cur_port=$( grep -oP '^PORT=\K.*' "$HAMLIB_SH" | tr -d '"' || echo "?")

# ── Read current username from .service files ─────────────────
cur_user=$(grep -hoP '/home/\K[^/]+' "${SERVICE_FILES[@]}" 2>/dev/null | sort -u | head -1 || echo "pi")

echo ""
echo -e "${BLD}=== Remote Radio Control — configuration ===${RST}"
echo ""

# ─────────────────────────────────────────────────────────────
# 1. CAT — serial port
# ─────────────────────────────────────────────────────────────
echo -e "${BLD}── Serial port (CAT) ───────────────────────────${RST}"

SERIAL_DIR="/dev/serial/by-id"
ports=()
if [ -d "$SERIAL_DIR" ]; then
    while IFS= read -r entry; do
        ports+=("$entry")
    done < <(ls -1 "$SERIAL_DIR" 2>/dev/null)
fi

if [ ${#ports[@]} -eq 0 ]; then
    warn "No devices found in $SERIAL_DIR"
    echo -en "${BLD}Enter full port path${RST} [${YEL}${cur_port}${RST}]: "
    read -r input
    new_port="${input:-$cur_port}"
else
    echo "Available devices:"
    for i in "${!ports[@]}"; do
        printf "  %2d) %s\n" "$((i+1))" "${ports[$i]}"
    done
    echo -e "   0) Enter manually"
    echo -en "${BLD}Select number or 0${RST} [${YEL}${cur_port}${RST}]: "
    read -r sel
    if [[ "$sel" =~ ^[1-9][0-9]*$ ]] && [ "$sel" -le "${#ports[@]}" ]; then
        new_port="${SERIAL_DIR}/${ports[$((sel-1))]}"
    elif [ "$sel" = "0" ]; then
        echo -en "${BLD}Enter full port path${RST}: "
        read -r new_port
    else
        new_port="$cur_port"
    fi
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 2. Baud rate
# ─────────────────────────────────────────────────────────────
echo -e "${BLD}── Baud rate ───────────────────────────────────${RST}"
common_bauds=(4800 9600 19200 38400 57600 115200)
echo "Common values:"
for i in "${!common_bauds[@]}"; do
    marker=""
    [ "${common_bauds[$i]}" = "$cur_baud" ] && marker=" ${GRN}← current${RST}"
    printf "  %d) %d%b\n" "$((i+1))" "${common_bauds[$i]}" "$marker"
done
echo -e "   0) Enter manually"
echo -en "${BLD}Select number or 0${RST} [${YEL}${cur_baud}${RST}]: "
read -r sel
if [[ "$sel" =~ ^[1-9][0-9]*$ ]] && [ "$sel" -le "${#common_bauds[@]}" ]; then
    new_baud="${common_bauds[$((sel-1))]}"
elif [ "$sel" = "0" ]; then
    echo -en "${BLD}Enter baud rate${RST}: "
    read -r new_baud
else
    new_baud="$cur_baud"
fi
echo ""

# ─────────────────────────────────────────────────────────────
# 3. Radio model (rigctld -m)
# ─────────────────────────────────────────────────────────────
echo -e "${BLD}── Radio model (rigctld) ───────────────────────${RST}"
echo "Popular Yaesu models:"
echo "  1046 – FT-450D        1054 – FT-991A        1080 – FTDX-3000"
echo "  1035 – FT-817/817ND   1085 – FT-710         1089 – FTDX-101D"
echo "  1036 – FT-847         1092 – FTDX-10        1090 – FTDX-101MP"
echo "  1040 – FT-857D        1066 – FT-2000        1073 – FTDX-5000"
echo "  1042 – FT-897D        1036 – FT-847"
echo "  (full list: rigctld --list)"
ask "Model number" "$cur_rig"
new_rig="$REPLY"
echo ""

# ─────────────────────────────────────────────────────────────
# 4. Username (paths in .service files)
# ─────────────────────────────────────────────────────────────
echo -e "${BLD}── Username (paths in .service files) ──────────${RST}"
ask "Username" "$cur_user"
new_user="$REPLY"
echo ""

# ─────────────────────────────────────────────────────────────
# Summary and confirmation
# ─────────────────────────────────────────────────────────────
echo -e "${BLD}── Summary ─────────────────────────────────────${RST}"
printf "  %-12s %s → %s\n" "Port:"      "$cur_port" "$new_port"
printf "  %-12s %s → %s\n" "Baud rate:" "$cur_baud" "$new_baud"
printf "  %-12s %s → %s\n" "Rig model:" "$cur_rig"  "$new_rig"
printf "  %-12s %s → %s\n" "User:"      "$cur_user" "$new_user"
echo ""
echo -en "${BLD}Apply changes? [Y/n]${RST}: "
read -r confirm
if [[ "$confirm" =~ ^[Nn]$ ]]; then
    warn "Aborted — no changes made."
    exit 0
fi
echo ""

# ─────────────────────────────────────────────────────────────
# Apply changes to startHamlib.sh
# ─────────────────────────────────────────────────────────────
info "Updating $HAMLIB_SH..."
updated=0

if [ "$new_port" != "$cur_port" ]; then
    sed -i "s|^PORT=.*|PORT=\"${new_port}\"|" "$HAMLIB_SH"
    changed "PORT = $new_port"
    updated=1
else
    skip "PORT"
fi

if [ "$new_baud" != "$cur_baud" ]; then
    sed -i "s|^BAUD=.*|BAUD=${new_baud}|" "$HAMLIB_SH"
    changed "BAUD = $new_baud"
    updated=1
else
    skip "BAUD"
fi

if [ "$new_rig" != "$cur_rig" ]; then
    sed -i "s|^RIG=.*|RIG=${new_rig}|" "$HAMLIB_SH"
    changed "RIG = $new_rig"
    updated=1
else
    skip "RIG"
fi

# ─────────────────────────────────────────────────────────────
# Install .service files (copy templates → systemd, apply user)
# ─────────────────────────────────────────────────────────────
info "Installing .service files to /etc/systemd/system/..."
for svc in "${SERVICE_FILES[@]}"; do
    svc_name="$(basename "$svc")"
    if [ "$new_user" != "$cur_user" ]; then
        sed "s|/home/${cur_user}/|/home/${new_user}/|g" "$svc" \
            | sudo tee "/etc/systemd/system/${svc_name}" >/dev/null
        changed "$svc_name (user → $new_user)"
        updated=1
    else
        sudo cp "$svc" "/etc/systemd/system/${svc_name}"
        changed "$svc_name"
    fi
done
sudo systemctl daemon-reload
ok ".service files installed & daemon reloaded"

# ─────────────────────────────────────────────────────────────
# Enable and start services
# ─────────────────────────────────────────────────────────────
sudo systemctl enable --now rrc_hamlib.service
ok "rrc_hamlib.service — enabled & started"

sudo systemctl enable --now rrc_node.service
ok "rrc_node.service — enabled & started"

warn "rrc_audio.service — installed but NOT enabled (Mumble is default)"

echo ""
if [ "$updated" -eq 1 ]; then
    ok "Configuration saved."
else
    ok "Nothing to change."
fi
echo ""

