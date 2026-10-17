#!/bin/bash
#--------------------------------------------------------
# install-panel.sh — ZIVPN web panel (login + user management)
# install.sh ကို အရင် run ထားပြီးသား ဖြစ်ရမယ်။
#
#   bash install-panel.sh
#   (non-interactive: ZVPN_ADMIN_USER / ZVPN_ADMIN_PASS / ZVPN_PANEL_PORT env)
#--------------------------------------------------------
set -e
RED='\033[1;31m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
[[ "$EUID" -ne 0 ]] && { echo -e "${RED}[x] root user နဲ့ run ပါ${NC}"; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/zvpn
[[ -f "$APP/zvpn.py" ]] || { echo -e "${RED}[x] ZIVPN မတပ်ရသေးပါ — အရင် bash install.sh ကို run ပါ${NC}"; exit 1; }

PORT="${ZVPN_PANEL_PORT:-}"
if [[ -z "$PORT" ]]; then
  read -r -p "Panel port (default 8088): " PORT
  PORT="${PORT:-8088}"
fi
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo -e "${RED}[x] port မှား${NC}"; exit 1; }

USER_NAME="${ZVPN_ADMIN_USER:-}"
PASS="${ZVPN_ADMIN_PASS:-}"
if [[ -z "$USER_NAME" ]]; then read -r -p "Admin username: " USER_NAME; fi
if [[ -z "$PASS" ]]; then
  read -r -s -p "Admin password (8+ လုံး): " PASS; echo
  read -r -s -p "Password ပြန်ရိုက်: " PASS2; echo
  [[ "$PASS" == "$PASS2" ]] || { echo -e "${RED}[x] password မတူပါ${NC}"; exit 1; }
fi
[[ ${#PASS} -ge 8 ]] || { echo -e "${RED}[x] password 8 လုံးနဲ့ အထက် ဖြစ်ရမယ်${NC}"; exit 1; }

echo -e "${YELLOW}[1/3] files...${NC}"
cp "$SRC/panel.py" "$APP/panel.py"
chmod +x "$APP/panel.py"

echo -e "${YELLOW}[2/3] admin login...${NC}"
ZVPN_PANEL_PORT="$PORT" python3 "$APP/panel.py" set-admin "$USER_NAME" "$PASS"

echo -e "${YELLOW}[3/3] service...${NC}"
cat > /etc/systemd/system/zvpn-panel.service <<SVC
[Unit]
Description=ZIVPN Web Panel
After=network.target zvpn-monitor.service

[Service]
Type=simple
User=root
Environment=ZVPN_PANEL_PORT=${PORT}
Environment=ZVPN_PANEL_BIND=0.0.0.0
ExecStart=/usr/bin/python3 ${APP}/panel.py serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVC
systemctl daemon-reload
systemctl enable --now zvpn-panel.service >/dev/null 2>&1
systemctl restart zvpn-panel.service
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "${PORT}/tcp" >/dev/null
fi
sleep 2
systemctl is-active --quiet zvpn-panel && S="active" || S="NOT running (journalctl -u zvpn-panel -n 30)"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  Panel: ${S}${NC}"
echo -e "${GREEN}  URL  : http://$(hostname -I | awk '{print $1}'):${PORT}${NC}"
echo -e "${GREEN}  Login: ${USER_NAME} / (သင်ရိုက်ထားတဲ့ password)${NC}"
echo -e "${GREEN}  ⚠ HTTP ဖြစ်တာမို့ IP allow-list (README) သုံးပါ${NC}"
echo -e "${GREEN}=========================================${NC}"
