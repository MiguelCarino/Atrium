#!/usr/bin/env bash
# Install (or update) the touchpad re-probe at boot and the watchdog that
# resets its I2C controller when it locks up. Run with sudo:
#     sudo ./system/touchpad-reprobe/install.sh   (from the Atrium repo; install.sh runs it)
# Only on a machine with an I2C HID device (ACPI PNP0C50, present: a laptop's
# touchpad or touchscreen); --force installs it anyway. Undo:
#     sudo systemctl disable --now touchpad-reprobe touchpad-watchdog
#     sudo rm /usr/local/libexec/touchpad-{reprobe,watchdog} /etc/systemd/system/touchpad-{reprobe,watchdog}.service
set -eu
here=$(cd "$(dirname "$0")" && pwd)
found=
for dev in /sys/bus/acpi/devices/PNP0C50:*; do
    [[ $(cat "$dev/status" 2>/dev/null) == 15 ]] && found=${dev##*/}
done
if [[ -z $found && ${1:-} != --force ]]; then
    echo "touchpad-reprobe: no I2C HID touchpad here; nothing to do"
    exit 0
fi
for name in touchpad-reprobe touchpad-watchdog; do
    install -D -m 0755 "$here/$name" "/usr/local/libexec/$name"
    install -D -m 0644 "$here/$name.service" "/etc/systemd/system/$name.service"
    # SELinux (Fedora): label the script like other local binaries so systemd may run it.
    command -v restorecon >/dev/null && restorecon "/usr/local/libexec/$name" || true
done
systemctl daemon-reload
systemctl enable --now touchpad-reprobe.service
systemctl enable touchpad-watchdog.service
systemctl restart touchpad-watchdog.service     # an update runs the new script
echo "touchpad-reprobe: on at every boot (journalctl -u touchpad-reprobe)"
echo "touchpad-watchdog: watching (journalctl -u touchpad-watchdog)"
