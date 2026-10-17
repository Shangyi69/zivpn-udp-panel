#!/bin/bash
# ZIVPN multi-user uninstaller. Usage: bash uninstall.sh [--keep-users]
[[ "$EUID" -ne 0 ]] && { echo "root user နဲ့ run ပါ"; exit 1; }
systemctl disable --now zvpn-monitor zivpn >/dev/null 2>&1
# remove DROP rules added by the monitor
iptables -S INPUT | grep zvpn-mu | sed 's/^-A INPUT //' | while read -r rule; do
  eval "iptables -D INPUT $rule" 2>/dev/null
done
rm -f /etc/systemd/system/zivpn.service /etc/systemd/system/zvpn-monitor.service
systemctl daemon-reload
rm -f /usr/local/bin/zivpn /usr/local/bin/zvpn
rm -rf /opt/zvpn /etc/zivpn
[[ "$1" == "--keep-users" ]] || rm -rf /etc/zivpn-mu
echo "ZIVPN multi-user ဖယ်ပြီးပါပြီ"
