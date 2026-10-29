#!/usr/bin/env bash
# Safer Fedora upgrade -- what a left click on the updates pill runs, in a
# terminal. In order:
#
#   1. snapshot   with snapper set up (hypr/scripts/setup-root.sh) nothing to
#                 do here: dnf itself takes a pre and a post snapshot around
#                 the upgrade, and snapshots.py can undo it. Without snapper:
#                 a read-only btrfs snapshot of / (the "root" subvolume; /home
#                 is its own subvolume and is not touched) in SNAPDIR,
#                 named pre-upgrade-<date>. KEEP of them are kept, older ones
#                 are deleted. It is not bootable by itself (no grub-btrfs
#                 here), but any file the upgrade breaks can be copied back
#                 from it, and the whole root can be rolled back from a live
#                 USB with `btrfs subvolume snapshot`.
#   2. dnf        sudo dnf upgrade --refresh, interactive as always.
#   3. nvidia     only on machines with the NVIDIA driver (skipped elsewhere: AMD and
#                 Intel drivers ship inside the kernel). The NVIDIA driver is
#                 an out-of-tree kernel module (akmod-nvidia from RPM Fusion),
#                 built per kernel. Rebooting into a new kernel that has no
#                 module -- or one built for an older driver than the userspace
#                 that just got installed -- is the black-screen-after-update
#                 classic. So: build it now (akmods --kernels), then verify
#                 `modinfo -k <newest kernel> nvidia` matches the installed
#                 driver version, and say plainly whether a reboot is safe.
#   4. flatpak    flatpak update -y (user + system).
#   5. firmware   fwupdmgr get-updates: listed only, never flashed from here.
#
# Then it pokes the updates pill (bar_signals.py "updates") so the count is right at once,
# and, once the record below is written, the reboot pill ("reboot", after a fresh
# needs-restarting), and records how it went for Settings > Software updates
# (hypr/scripts/software-updates.py reads it) in
# $XDG_STATE_HOME/hypr/last-upgrade.tsv -- tab-separated "key<TAB>value" lines:
#     finished <epoch>   dnf <dnf's exit status>
#     kernel_before / kernel_after <version-release.arch>   running <uname -r>
#     driver <xorg-x11-drv-nvidia version>   module <nvidia module version>
#     nvidia ok|missing|mismatch|none   reboot safe|unsafe|not-needed
# Written when the run gets that far (not if you stop it at the snapshot
# question), atomically (tmp + mv).

set -u
KEEP=3
SNAPDIR=/.snapshots-pre-upgrade     # /.snapshots is snapper's once it is set up
bold=$'\e[1m' red=$'\e[1;31m' green=$'\e[1;32m' yellow=$'\e[1;33m' off=$'\e[0m'

step() { printf '\n%s== %s ==%s\n' "$bold" "$1" "$off"; }
newest_kernel() { rpm -q --qf '%{BUILDTIME} %{VERSION}-%{RELEASE}.%{ARCH}\n' kernel-core | sort -n | tail -1 | cut -d' ' -f2; }

step "1/5  btrfs snapshot of /"
if snapper -c root list >/dev/null 2>&1; then
    echo "  snapper: dnf takes a pre / post snapshot around this upgrade by itself"
elif [[ $(findmnt -no FSTYPE /) == btrfs ]]; then
    snap="$SNAPDIR/pre-upgrade-$(date +%Y-%m-%d_%H%M)"
    if sudo mkdir -p "$SNAPDIR" && sudo btrfs subvolume snapshot -r / "$snap" >/dev/null; then
        echo "  $snap"
        # Oldest first; everything but the newest KEEP goes.
        mapfile -t old < <(sudo find "$SNAPDIR" -maxdepth 1 -name 'pre-upgrade-*' | sort | head -n -"$KEEP")
        for s in "${old[@]}"; do
            sudo btrfs subvolume delete "$s" >/dev/null && echo "  removed old $s"
        done
    else
        printf '%s  snapshot failed -- continue without one? [y/N] %s' "$yellow" "$off"
        read -r ans; [[ $ans == y ]] || exit 1
    fi
else
    echo "  / is not btrfs; skipped"
fi

step "2/5  dnf upgrade"
kernel_before=$(newest_kernel)
sudo dnf upgrade --refresh
dnf_rc=$?
kernel_after=$(newest_kernel)

step "3/5  Out-of-tree GPU driver for the newest kernel ($kernel_after)"
driver=$(rpm -q --qf '%{VERSION}\n' xorg-x11-drv-nvidia 2>/dev/null | sort -V | tail -1)
safe=1
nvidia=none module=
if [[ -z $driver || $driver == *"not installed"* ]]; then
    driver=
    echo "  no out-of-tree GPU driver (NVIDIA akmod) installed; nothing to check"
else
    [[ $kernel_after != "$kernel_before" ]] && echo "  new kernel: $kernel_before -> $kernel_after"
    # Builds only what is missing or stale; a no-op when all is in place.
    sudo akmods --kernels "$kernel_after" 2>&1 | sed 's/^/  /'
    module=$(modinfo -k "$kernel_after" -F version nvidia 2>/dev/null)
    if [[ -z $module ]]; then
        safe=0 nvidia=missing; echo "  ${red}no nvidia module for $kernel_after${off}"
    elif [[ $module != "$driver" ]]; then
        safe=0 nvidia=mismatch; echo "  ${red}module $module does not match driver $driver${off}"
    else
        nvidia=ok; echo "  ${green}module $module = driver $driver${off}"
    fi
fi

step "4/5  flatpak"
flatpak update -y 2>&1 | tail -n 15 | sed 's/^/  /'

step "5/5  firmware (list only)"
fwupdmgr get-updates --no-unreported-check 2>/dev/null | sed 's/^/  /' || echo "  none, or fwupd unavailable"

"$HOME/.config/hypr/scripts/bar_signals.py" poke updates 2>/dev/null

if ((!safe)); then reboot=unsafe
elif [[ $kernel_after != "$(uname -r)" ]]; then reboot=safe
else reboot=not-needed
fi
record="${XDG_STATE_HOME:-$HOME/.local/state}/hypr/last-upgrade.tsv"
mkdir -p "${record%/*}" && {
    printf 'finished\t%s\n' "$EPOCHSECONDS"
    printf 'dnf\t%s\n' "$dnf_rc"
    printf 'kernel_before\t%s\n' "$kernel_before"
    printf 'kernel_after\t%s\n' "$kernel_after"
    printf 'running\t%s\n' "$(uname -r)"
    printf 'driver\t%s\n' "$driver"
    printf 'module\t%s\n' "$module"
    printf 'nvidia\t%s\n' "$nvidia"
    printf 'reboot\t%s\n' "$reboot"
} > "$record.tmp" && mv -f "$record.tmp" "$record"

# The reboot pill: needs-restarting asked afresh (its 30-min cache predates
# this upgrade; it takes seconds, so detached, outliving this terminal),
# then bar_signals.py "reboot" redraws it.
setsid -f sh -c '"$HOME/.config/waybar/scripts/reboot_needed.py" refresh >/dev/null 2>&1
                 "$HOME/.config/hypr/scripts/bar_signals.py" poke reboot >/dev/null 2>&1' \
    </dev/null >/dev/null 2>&1

echo
if ((safe)); then
    if [[ $kernel_after != "$(uname -r)" ]]; then
        echo "${green}Safe to reboot${off} into $kernel_after."
    else
        echo "${green}Done.${off} Still on the newest kernel; no reboot needed for it."
    fi
else
    echo "${red}DO NOT REBOOT YET.${off} The new kernel has no working NVIDIA module."
    echo "Try: sudo akmods --force --kernels $kernel_after   and check its log under /var/cache/akmods/"
    echo "The previous kernel ($(uname -r)) still works: pick it in the boot menu if you must reboot."
fi
printf '\nPress Enter to close. '
read -r _
