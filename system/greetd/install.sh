#!/usr/bin/env bash
# Install greetd + tuigreet as the login screen. Run with sudo:
#     sudo ./system/greetd/install.sh            (install.sh runs it when there is no login screen)
#     sudo ./system/greetd/install.sh --replace  (switch from GDM, SDDM, ...: that one is disabled)
# Undo:
#     sudo systemctl disable greetd && sudo systemctl enable <your old one, e.g. gdm>
#     sudo mv /etc/greetd/config.toml.atrium-backup /etc/greetd/config.toml   (if there is one)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
replace=0
[[ ${1:-} == --replace ]] && replace=1
current=$(systemctl show -p Id --value display-manager.service 2>/dev/null || true)
if [[ -n $current && $current != display-manager.service && $current != greetd.service ]]; then
    if (( ! replace )); then
        echo "A login screen is set up already ($current); kept. --replace switches to greetd."
        exit 0
    fi
    systemctl disable "$current"
fi
rpm -q greetd tuigreet >/dev/null || dnf install -y greetd tuigreet
id greetd >/dev/null 2>&1 || useradd -r -M -d /var/lib/greetd -s /sbin/nologin -G video greetd
conf=/etc/greetd/config.toml
if [[ -f $conf ]] && ! cmp -s "$here/config.toml" "$conf"; then
    [[ -e $conf.atrium-backup ]] || cp -a "$conf" "$conf.atrium-backup"
fi
install -D -m 0644 "$here/config.toml" "$conf"
# tuigreet's --remember keeps the last user and session here
install -d -m 0755 -o greetd -g greetd /var/cache/tuigreet
systemctl enable greetd.service
systemctl set-default graphical.target
echo "greetd is the login screen from the next boot."
