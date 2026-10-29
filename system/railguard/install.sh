#!/usr/bin/env bash
# Install (or update) railguard's system part: the SysRq keys. Run with sudo:
#     sudo ./system/railguard/install.sh   (from the Atrium repo; install.sh runs it)
# The rest of railguard is the user's (~/.config/systemd/user/agents.slice,
# railguard.service, ~/.config/hypr/scripts/railguard.py) and needs no root.
# Undo:
#     sudo rm /etc/sysctl.d/90-railguard-sysrq.conf && sudo sysctl kernel.sysrq=16
set -eu
here=$(cd "$(dirname "$0")" && pwd)
install -D -m 0644 "$here/90-railguard-sysrq.conf" /etc/sysctl.d/90-railguard-sysrq.conf
command -v restorecon >/dev/null && restorecon /etc/sysctl.d/90-railguard-sysrq.conf || true
sysctl -p /etc/sysctl.d/90-railguard-sysrq.conf
