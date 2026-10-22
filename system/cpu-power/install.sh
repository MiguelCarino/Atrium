#!/usr/bin/env bash
# Install (or update) the cpu-power service. Run with sudo:
#     sudo ./system/cpu-power/install.sh   (from the Atrium repo; install.sh runs it)
# Undo:
#     sudo systemctl disable --now cpu-power
#     sudo rm /usr/local/libexec/cpu-power /etc/systemd/system/cpu-power.service
set -eu
here=$(cd "$(dirname "$0")" && pwd)
install -D -m 0755 "$here/cpu-power" /usr/local/libexec/cpu-power
install -D -m 0644 "$here/cpu-power.service" /etc/systemd/system/cpu-power.service
# SELinux (Fedora): label the script like other local binaries so systemd may run it.
command -v restorecon >/dev/null && restorecon /usr/local/libexec/cpu-power || true
systemctl daemon-reload
systemctl enable --now cpu-power.service
sleep 6
echo "CPU package power: $(cat /run/cpu-power/watts 2>/dev/null || echo 'not yet -- see: journalctl -u cpu-power') W"
