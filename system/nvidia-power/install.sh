#!/usr/bin/env bash
# Install (or update) the NVIDIA offload card's runtime power management.
# Run with sudo:
#     sudo ./system/nvidia-power/install.sh   (from the Atrium repo; install.sh runs it)
# Only on a machine with an NVIDIA card that has no screens of its own (PCI
# class 0x0302, "3D controller": a hybrid laptop's offload card). A card that
# drives the screens is never idle, so this would do nothing there; --force
# installs it anyway. Undo:
#     sudo rm /etc/modprobe.d/nvidia-runtime-pm.conf   (and reboot)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
offload=
for dev in /sys/bus/pci/devices/*; do
    [[ $(cat "$dev/vendor" 2>/dev/null) == 0x10de && $(cat "$dev/class" 2>/dev/null) == 0x0302* ]] && offload=${dev##*/}
done
if [[ -z $offload && ${1:-} != --force ]]; then
    echo "nvidia-power: no NVIDIA offload card here (a 3D controller without screens); nothing to do"
    exit 0
fi
install -D -m 0644 "$here/nvidia-runtime-pm.conf" /etc/modprobe.d/nvidia-runtime-pm.conf
command -v restorecon >/dev/null && restorecon /etc/modprobe.d/nvidia-runtime-pm.conf || true
# Only if a dracut config put the driver in the initramfs: rebuild it, or the
# option would not reach the module loaded from there.
if command -v lsinitrd >/dev/null && lsinitrd 2>/dev/null | grep -q '/nvidia\.ko'; then
    dracut -f
fi
echo "nvidia-power: runtime power management for ${offload:-the NVIDIA card} on from the next boot."
echo "  check after rebooting: grep 'Runtime D3' /proc/driver/nvidia/gpus/*/power"
