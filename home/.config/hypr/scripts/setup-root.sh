#!/usr/bin/env bash
# The system-side half of the desktop: what needs root, once per machine.
# Safe to run again (every step checks first).
#
#   sudo ~/.config/hypr/scripts/setup-root.sh
#
#   1. snapper   automatic btrfs snapshots of / (the "root" subvolume; /home
#                is its own subvolume and is not included):
#                  * a pre and a post snapshot around EVERY dnf transaction
#                    (libdnf5-plugin-actions, /etc/dnf/libdnf5-plugins/
#                    actions.d/snapper.actions), so any update can be undone
#                  * a timeline: hourly, kept 5 hourly / 7 daily / 2 weekly
#                  * at most NUMBER_LIMIT update snapshots
#                ALLOW_USERS lets you list / compare / undo without sudo
#                (snapshots.py, the bar's snapshots panel).
#                safe-upgrade.sh's own pre-upgrade-* snapshots used to live in
#                /.snapshots, which snapper needs for itself: they are moved,
#                untouched, to /.snapshots-pre-upgrade.
#                Skipped when / is not btrfs.
#   2. KDE Connect  kdeconnectd (the phone link, phone.py) and its firewall
#                ports (firewalld's "kdeconnect" service, 1714-1764 tcp+udp).
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "run it with sudo"; exit 1; }
# The desktop's user: the one who ran sudo (else the login name of this
# terminal). Never root itself: ALLOW_USERS and the rest are for you.
USER_NAME=${SUDO_USER:-$(logname 2>/dev/null || true)}
if [[ -z $USER_NAME || $USER_NAME == root ]]; then
    echo "run it with sudo from your own account (SUDO_USER is not set, so whose desktop this is is unknown)"
    exit 1
fi

say() { printf '\n\e[1m== %s ==\e[0m\n' "$1"; }

say "packages"
dnf install -y snapper libdnf5-plugin-actions kdeconnectd

say "KDE Connect: firewall"
if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=kdeconnect >/dev/null
    firewall-cmd --reload >/dev/null
    echo "  kdeconnect ports open"
fi

say "snapper: is / btrfs?"
# snapper snapshots btrfs subvolumes only: on ext4 / xfs (or in a container)
# there is nothing to snapshot, and the rest of this script is snapper.
if [[ $(findmnt -no FSTYPE / 2>/dev/null) != btrfs ]]; then
    echo "  / is $(findmnt -no FSTYPE / 2>/dev/null || echo unknown), not btrfs: no snapshots"
    echo
    echo "Done. Now open KDE Connect on the phone (same Wi-Fi) and pair with this computer."
    exit 0
fi

say "snapper: config for /"
if ! snapper -c root list >/dev/null 2>&1; then
    if [[ -d /.snapshots ]]; then
        echo "  moving the old pre-upgrade snapshots to /.snapshots-pre-upgrade"
        mkdir -p /.snapshots-pre-upgrade
        for s in /.snapshots/*; do
            [[ -e $s ]] || continue
            # A read-only snapshot cannot be moved to another folder (its ".."
            # would change): make it writable for the move, then read-only again.
            ro=$(btrfs property get -ts "$s" ro 2>/dev/null | cut -d= -f2)
            [[ $ro == true ]] && btrfs property set -ts "$s" ro false
            mv "$s" /.snapshots-pre-upgrade/
            [[ $ro == true ]] && btrfs property set -ts "/.snapshots-pre-upgrade/$(basename "$s")" ro true
        done
        rmdir /.snapshots
    fi
    snapper -c root create-config /
fi
snapper -c root set-config \
    ALLOW_USERS="$USER_NAME" SYNC_ACL=yes \
    TIMELINE_CREATE=yes TIMELINE_CLEANUP=yes \
    TIMELINE_LIMIT_HOURLY=5 TIMELINE_LIMIT_DAILY=7 TIMELINE_LIMIT_WEEKLY=2 \
    TIMELINE_LIMIT_MONTHLY=0 TIMELINE_LIMIT_YEARLY=0 \
    NUMBER_CLEANUP=yes NUMBER_LIMIT=20 NUMBER_LIMIT_IMPORTANT=10
systemctl enable --now snapper-timeline.timer snapper-cleanup.timer

say "snapper: a snapshot around every dnf transaction"
mkdir -p /etc/dnf/libdnf5-plugins/actions.d
cat > /etc/dnf/libdnf5-plugins/actions.d/snapper.actions <<'EOF'
# Written by ~/.config/hypr/scripts/setup-root.sh: a snapper pre snapshot
# before each dnf transaction and its post snapshot after, described by the
# dnf command line, so `snapper undochange PRE..POST` can undo it.
pre_transaction::::/usr/bin/sh -c echo\ "tmp.cmd=$(ps\ -o\ command\ --no-headers\ -p\ '${pid}')"
pre_transaction::::/usr/bin/sh -c echo\ "tmp.snapper_pre_number=$(snapper\ create\ -t\ pre\ -c\ number\ -p\ -d\ "${tmp.cmd}")"
post_transaction::::/usr/bin/sh -c [\ -n\ "${tmp.snapper_pre_number}"\ ]\ &&\ snapper\ create\ -t\ post\ --pre-number\ "${tmp.snapper_pre_number}"\ -c\ number\ -d\ "${tmp.cmd}"\ ;\ echo\ tmp.snapper_pre_number\ ;\ echo\ tmp.cmd
EOF
grep -q '^enabled *= *1' /etc/dnf/libdnf5-plugins/actions.conf 2>/dev/null ||
    printf '[main]\nname = actions\nenabled = 1\n' > /etc/dnf/libdnf5-plugins/actions.conf

say "first snapshot"
snapper -c root create -d "setup-root.sh" -c number
snapper -c root list | tail -3
echo
echo "Done. Now open KDE Connect on the phone (same Wi-Fi) and pair with this computer."
echo "kdeconnectd starts with your next login; to start it now: /usr/bin/kdeconnectd &"
