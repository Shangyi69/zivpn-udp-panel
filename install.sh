#!/bin/bash
#--------------------------------------------------------
# ZIVPN multi-user installer (based on udp-zivpn zi.sh)
#   bash install.sh
#--------------------------------------------------------
set -e
RED='\033[1;31m'; GREEN='\033[1;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
[[ "$EUID" -ne 0 ]] && { echo -e "${RED}[x] root user နဲ့ run ပါ${NC}"; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/zvpn
BIN=/usr/local/bin/zivpn
ZIVPN_PORT=5667
DNAT_RANGE="6000:19999"

case "$(uname -m)" in
  x86_64)  ZBIN_URL="https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/udp-zivpn-linux-amd64" ;;
  aarch64|arm64) ZBIN_URL="https://github.com/zahidbd2/udp-zivpn/releases/download/udp-zivpn_1.4.9/udp-zivpn-linux-arm64" ;;
  *) echo -e "${RED}[x] unsupported arch: $(uname -m)${NC}"; exit 1 ;;
esac

echo -e "${YELLOW}[1/7] packages...${NC}"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y >/dev/null
apt-get install -y python3 conntrack iptables iptables-persistent openssl wget >/dev/null

echo -e "${YELLOW}[2/7] ZIVPN binary...${NC}"
# binary အသုံးပြုနေရင် "Text file busy" ဖြစ်တတ်လို့ အရင် ရပ်ထား
systemctl stop zvpn-monitor zivpn >/dev/null 2>&1 || true
wget -q "$ZBIN_URL" -O "$BIN" || { echo -e "${RED}[x] binary download မအောင်မြင်ပါ${NC}"; exit 1; }
chmod +x "$BIN"

echo -e "${YELLOW}[3/7] certificate...${NC}"
mkdir -p /etc/zivpn
if [[ ! -f /etc/zivpn/zivpn.crt || ! -f /etc/zivpn/zivpn.key ]]; then
  openssl req -new -newkey rsa:4096 -days 365 -nodes -x509 -subj "/C=US/ST=CA/L=LA/O=ZIVPN/OU=IT/CN=zivpn" \
    -keyout /etc/zivpn/zivpn.key -out /etc/zivpn/zivpn.crt 2>/dev/null
fi

echo -e "${YELLOW}[4/7] app + config...${NC}"
mkdir -p "$APP"
cp "$SRC/zvpn.py" "$APP/zvpn.py"
chmod +x "$APP/zvpn.py"
ln -sf "$APP/zvpn.py" /usr/local/bin/zvpn
# placeholder config; zvpn sync fills auth.config from users
cat > /etc/zivpn/config.json <<CFG
{
  "listen": ":${ZIVPN_PORT}",
  "cert": "/etc/zivpn/zivpn.crt",
  "key": "/etc/zivpn/zivpn.key",
  "obfs": "zivpn",
  "auth": { "mode": "passwords", "config": ["zv-placeholder"] }
}
CFG
python3 "$APP/zvpn.py" sync >/dev/null

echo -e "${YELLOW}[5/7] firewall + port range...${NC}"
IFACE=$(ip -4 route ls | grep default | grep -Po '(?<=dev )(\S+)' | head -1)
RULE=(-i "$IFACE" -p udp --dport "$DNAT_RANGE" -j DNAT --to-destination ":${ZIVPN_PORT}")
iptables -t nat -C PREROUTING "${RULE[@]}" 2>/dev/null || iptables -t nat -A PREROUTING "${RULE[@]}"
iptables -C INPUT -p udp --dport "$ZIVPN_PORT" -j ACCEPT 2>/dev/null || iptables -I INPUT -p udp --dport "$ZIVPN_PORT" -j ACCEPT
netfilter-persistent save >/dev/null 2>&1 || true
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow "${ZIVPN_PORT}/udp" >/dev/null
  ufw allow "${DNAT_RANGE}/udp" >/dev/null
fi

echo -e "${YELLOW}[6/7] services...${NC}"
cat > /etc/systemd/system/zivpn.service <<'SVC'
[Unit]
Description=ZIVPN UDP Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/etc/zivpn
ExecStart=/usr/local/bin/zivpn server -c /etc/zivpn/config.json
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
SVC
cat > /etc/systemd/system/zvpn-monitor.service <<SVC
[Unit]
Description=ZIVPN multi-user monitor (expiry, online, device limit)
After=zivpn.service

[Service]
Type=simple
User=root
ExecStart=/usr/bin/python3 ${APP}/zvpn.py monitor
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SVC
systemctl daemon-reload
systemctl enable --now zivpn.service zvpn-monitor.service >/dev/null 2>&1
systemctl restart zivpn.service

echo -e "${YELLOW}[7/7] check...${NC}"
sleep 2
systemctl is-active --quiet zivpn && Z="active" || Z="NOT running (journalctl -u zivpn -n 30)"
systemctl is-active --quiet zvpn-monitor && M="active" || M="NOT running (journalctl -u zvpn-monitor -n 30)"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}  ZIVPN multi-user ပြီးပါပြီ${NC}"
echo -e "${GREEN}  zivpn        : ${Z}${NC}"
echo -e "${GREEN}  zvpn-monitor : ${M}${NC}"
echo -e "${GREEN}  Server       : $(hostname -I | awk '{print $1}'):${ZIVPN_PORT}  (ports ${DNAT_RANGE} ကိုလည်း သုံးနိုင်)${NC}"
echo -e "${GREEN}  Menu         : zvpn${NC}"
echo -e "${GREEN}=========================================${NC}"
