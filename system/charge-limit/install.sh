#!/usr/bin/env bash
# Install (or update) the battery charge limit. Run with sudo:
#     sudo ./system/charge-limit/install.sh [--limit N]   (from the Atrium repo; install.sh runs it)
# Only on a machine whose battery has a charge limit switch
# (charge_control_end_threshold: a laptop with asus-wmi, thinkpad_acpi,
# dell-laptop, ...); a desktop or a laptop without one gets nothing.
# --force installs it anyway.
#
# Installing changes nothing about charging: until a limit is chosen
# (Settings > Battery, `charge-limit.py set 80`, or --limit N here) no limit
# is saved and the firmware charges to full as before. What it installs:
#   /usr/local/libexec/charge-limit           the root helper (apply | set N)
#   charge-limit.service                      writes the saved limit at boot and after resume
#   charge-limit@.service                     the session's way to set one (started, never enabled)
#   /etc/polkit-1/rules.d/50-atrium-charge-limit.rules
#                                             lets the active local session start charge-limit@50..100
#   /etc/atrium/charge-limit                  the saved limit (written by the helper)
#   /etc/atrium/charge-limit-choices          fixed values learned (or written by hand:
#                                             "60 80 100"; "any" opts an ASUS out of 60/80/100)
#   /etc/atrium/charge-limit-start            a start threshold the helper moved, to restore it
# Undo:
#     sudo systemctl disable charge-limit.service
#     sudo rm /usr/local/libexec/charge-limit /etc/systemd/system/charge-limit{,@}.service \
#             /etc/polkit-1/rules.d/50-atrium-charge-limit.rules /etc/atrium/charge-limit{,-choices,-start}
#     (then the firmware's own limit is back at the next boot; on most, full)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
usage() { echo "usage: $0 [--force] [--limit N]   (N: a whole number, 50-100)" >&2; exit 2; }
force= limit=
while (( $# )); do
    case $1 in
    --force) force=1 ;;
    --limit) (( $# >= 2 )) || usage; limit=$2; shift ;;
    *) usage ;;
    esac
    shift
done
# Checked before anything is installed: N becomes a unit name
# (charge-limit@N.service), and the same digits the polkit rule and the
# helper take -- no leading zero, no "%".
if [[ -n $limit && ! $limit =~ ^(5[0-9]|[6-9][0-9]|100)$ ]]; then
    echo "charge-limit: not a limit: '$limit'" >&2
    usage
fi
found=
for bat in /sys/class/power_supply/*; do
    [[ $(cat "$bat/type" 2>/dev/null) == Battery && $(cat "$bat/scope" 2>/dev/null) != Device &&
       $(cat "$bat/present" 2>/dev/null) != 0 && -e $bat/charge_control_end_threshold ]] && found=${bat##*/}
done
if [[ -z $found && -z $force ]]; then
    echo "charge-limit: no battery here can stop charging short of full; nothing to do"
    exit 0
fi
install -D -m 0755 "$here/charge-limit" /usr/local/libexec/charge-limit
install -D -m 0644 "$here/charge-limit.service" /etc/systemd/system/charge-limit.service
install -D -m 0644 "$here/charge-limit@.service" /etc/systemd/system/charge-limit@.service
install -D -m 0644 "$here/50-atrium-charge-limit.rules" /etc/polkit-1/rules.d/50-atrium-charge-limit.rules
install -d -m 0755 /etc/atrium
# SELinux (Fedora): label them like other local binaries / rules so systemd
# may run the helper and polkitd may read the rule.
command -v restorecon >/dev/null &&
    restorecon /usr/local/libexec/charge-limit /etc/polkit-1/rules.d/50-atrium-charge-limit.rules /etc/atrium || true
systemctl daemon-reload
# Enabled, not started: starting it now would only write a limit already
# saved (an update), which the next line does anyway when there is one.
systemctl enable charge-limit.service
if [[ -n $limit ]]; then
    # A refusal (firmware that takes none of it) must not abort before the
    # summary: say where the helper's reason is.
    systemctl start "charge-limit@$limit.service" ||
        echo "charge-limit: could not set $limit% -- journalctl -u charge-limit@$limit.service" >&2
elif [[ -s /etc/atrium/charge-limit ]]; then
    systemctl start charge-limit.service || true     # an update: the saved limit, by the new helper
fi
saved=$(cat /etc/atrium/charge-limit 2>/dev/null || true)
if [[ -n $saved ]]; then
    echo "charge-limit: ${found:-the battery} stops charging at $saved%"
else
    echo "charge-limit: ${found:-the battery} charges to full (no limit chosen yet)"
fi
echo "  change it: Settings > Battery, or ~/.config/hypr/scripts/charge-limit.py set 80"
