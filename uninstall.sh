#!/usr/bin/env bash
# Atrium: put back what install.sh replaced. install.sh copies each of your
# ~/.config/hypr, waybar, mako, ... that it is about to change into
# ~/.local/share/atrium/backup-<date>/ (step 3) before copying the desktop
# in; this restores those copies.
#
#   ./uninstall.sh --dry-run          only prints what it would do (start here)
#   ./uninstall.sh                    asks before each step
#   ./uninstall.sh --yes              takes every default answer
#   ./uninstall.sh --list             the backups there are, and what each holds
#   ./uninstall.sh --backup DIR       restore from that one backup only
#   ./uninstall.sh --keep-services    leave the user services as they are
#
# Steps:
#   1. services   stop and disable the user services install.sh enabled
#                 (packages/units.txt)
#   2. restore    every path a backup holds goes back where it was. With
#                 several backups (install.sh run more than once) each path
#                 comes from the OLDEST backup that has it -- the copy made
#                 before Atrium first touched it. --backup picks one instead.
#   3. new files  the desktop's folders you did not have before (no backup
#                 holds them, e.g. ~/.config/waybar on a fresh account) --
#                 only with a yes; default no
# Nothing is deleted: whatever is in the way (Atrium's version) is MOVED to
# ~/.local/share/atrium/removed-<date>/, so this can be undone by hand too.
#
# Not touched: the packages (dnf history undo, or remove them by name), the
# root-side pieces (system/*: `sudo rm` the files each install.sh lists),
# your own files the desktop never shipped, and the backups themselves.
# Log out of Hyprland first: the bar and the services read these files.
set -uo pipefail

REPO=$(cd "$(dirname "$0")" && pwd)
DATA=$HOME/.local/share/atrium
STAMP=$(date +%Y%m%d-%H%M%S)
AWAY=$DATA/removed-$STAMP
DRY=0 YES=0 LIST=0 ONLY="" SERVICES=1
while (( $# )); do
    case $1 in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --list) LIST=1 ;;
    --keep-services) SERVICES=0 ;;
    --backup) ONLY=${2:-}; shift ;;
    *) sed -n '2,30p' "$0"; exit 2 ;;
    esac
    shift
done

bold=$'\e[1m' dim=$'\e[2m' yellow=$'\e[1;33m' off=$'\e[0m'
step() { printf '\n%s== %s ==%s\n' "$bold" "$1" "$off"; }
note() { printf '  %s\n' "$*"; }
run() {  # print, then run unless --dry-run; a failure is reported, not fatal
    printf '%s$ %s%s\n' "$dim" "$*" "$off"
    (( DRY )) && return 0
    "$@" || { printf '%s  (failed: %s)%s\n' "$yellow" "$*" "$off"; return 1; }
}
ask() {  # ask "question" y|n -> 0 for yes; --yes takes the default
    local q=$1 def=$2 hint reply
    [[ $def == y ]] && hint="[Y/n]" || hint="[y/N]"
    if (( YES || DRY )) || [[ ! -t 0 ]]; then
        printf '  %s %s %s\n' "$q" "$hint" "$def"
        [[ $def == y ]]
        return
    fi
    read -rp "  $q $hint " reply
    reply=${reply:-$def}
    [[ ${reply,,} == y* ]]
}
list() { grep -v '^\s*#' "$1" | sed 's/#.*//; s/\s*$//' | grep -v '^$'; }

# The paths a backup holds: what install.sh copied, i.e. .config/<x> and
# .local/share/fonts (the same `ls -d` install.sh runs on the repo).
held() {   # held <backup dir>
    (cd "$1" 2>/dev/null && ls -d .config/* .local/share/fonts 2>/dev/null)
}

# put_aside <path under $HOME>: move the current one to $AWAY (keeping its place)
put_aside() {
    [[ -e $HOME/$1 || -L $HOME/$1 ]] || return 0
    run mkdir -p "$AWAY/$(dirname "$1")"
    run mv "$HOME/$1" "$AWAY/$1"
}

[[ $EUID -ne 0 ]] || { echo "Run this as yourself, not root."; exit 1; }

mapfile -t backups < <(ls -d "$DATA"/backup-* 2>/dev/null | sort)
if [[ -n $ONLY ]]; then
    [[ -d $ONLY ]] || { echo "No backup folder $ONLY"; exit 1; }
    backups=("$(cd "$ONLY" && pwd)")
fi

if (( LIST )); then
    (( ${#backups[@]} )) || { echo "No backups in $DATA (install.sh found nothing of yours to replace)."; exit 0; }
    for b in "${backups[@]}"; do
        printf '%s%s%s\n' "$bold" "$b" "$off"
        held "$b" | sed 's/^/  ~\//'
    done
    exit 0
fi

printf '%sAtrium uninstall%s\n' "$bold" "$off"
(( DRY )) && note "(dry run: nothing is changed)"
if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]] && (( ! DRY )); then
    note "Hyprland is running: the bar and the services may rewrite files while this runs."
    ask "Go on anyway? (better: log out, switch to a text console, run it there)" n || exit 1
fi

step "1/3  services"
if (( ! SERVICES )); then
    note "kept as they are (--keep-services)"
elif [[ -r $REPO/packages/units.txt ]] && ask "Stop and disable the desktop's user services?" y; then
    while read -r unit; do
        run systemctl --user disable --now "$unit"
    done < <(list "$REPO/packages/units.txt")
    # Enabled by the desktop itself later (Settings switches, the welcome):
    for unit in welcome.service railguard.service; do
        systemctl --user is-enabled "$unit" >/dev/null 2>&1 && run systemctl --user disable --now "$unit"
    done
fi

step "2/3  restore"
declare -A from=()
if (( ${#backups[@]} == 0 )); then
    note "No backups in $DATA: install.sh found nothing of yours to replace."
else
    # Oldest first, and the first backup to hold a path wins.
    for b in "${backups[@]}"; do
        while read -r p; do
            [[ -n $p && -z ${from[$p]:-} ]] && from[$p]=$b
        done < <(held "$b")
    done
    mapfile -t paths < <(printf '%s\n' "${!from[@]}" | sort)
    for p in "${paths[@]}"; do
        note "~/$p  <-  ${from[$p]##*/}"
    done
    if ask "Put these ${#paths[@]} back (the current ones move to ${AWAY/#$HOME/\~})?" y; then
        for p in "${paths[@]}"; do
            put_aside "$p"
            run mkdir -p "$HOME/$(dirname "$p")"
            run cp -a "${from[$p]}/$p" "$HOME/$p"
        done
    fi
fi

step "3/3  new files"
mapfile -t shipped < <(cd "$REPO/home" 2>/dev/null && ls -d .config/* .local/share/fonts 2>/dev/null)
fresh=()
for p in "${shipped[@]}"; do
    [[ -z ${from[$p]:-} && -e $HOME/$p ]] && fresh+=("$p")
done
if (( ${#fresh[@]} == 0 )); then
    note "nothing of the desktop's is left that you did not have before"
else
    note "The desktop's, with no backup (you did not have them before -- or they were"
    note "identical to Atrium's, which only happens when install.sh ran twice):"
    printf '    ~/%s\n' "${fresh[@]}"
    if ask "Move these out of the way too?" n; then
        for p in "${fresh[@]}"; do
            put_aside "$p"
        done
    fi
fi

if (( ! DRY )) && [[ -d $AWAY ]]; then
    note "Atrium's files are in ${AWAY/#$HOME/\~}; delete that folder once you are sure."
fi
(( DRY )) || run systemctl --user daemon-reload
printf '\n%sDone.%s Log out; pick your previous session at the login screen.\n' "$bold" "$off"
note "Packages stay installed: \`dnf history list\` shows the install.sh transaction to undo."
