#!/usr/bin/env bash
# Atrium: the setup for a new user. Fedora 44 or newer, an ordinary
# user account that may use sudo, then
#
#   git clone https://github.com/MiguelCarino/Atrium ~/Atrium && ~/Atrium/install.sh
#
#   ./install.sh             asks before each step that is optional
#   ./install.sh --yes       takes every default answer without asking
#   ./install.sh --dry-run   only prints what it would do
#
# Steps, each safe to run again:
#   1. repositories   rpmfusion free + nonfree, the coprs in packages/repos.txt
#   2. packages       packages/dnf.txt (names a release lacks are skipped),
#                     then the graphics card's own: it reads which cards
#                     there are (NVIDIA, AMD, Intel, none) and offers the
#                     driver and video-encoding packages for those only --
#                     the NVIDIA driver (akmod-nvidia) only on an NVIDIA
#                     card, VA-API on AMD / Intel -- and says what works
#                     less well without a card or without LM Studio
#   3. your config    any of ~/.config/hypr, waybar, mako, ... that already
#                     exists is COPIED to a dated backup folder first; then the
#                     desktop's files are copied in (nothing of yours deleted)
#   4. your folders   where your projects live (~/.config/hypr/desktop.conf)
#   5. system side    optional: btrfs snapshots around every update (snapper)
#                     and the phone link's firewall ports (KDE Connect);
#                     the CPU power reading for the bar (cpu-power); the
#                     SysRq keys that end a freeze without a reset (railguard);
#                     a login screen (greetd + tuigreet) when there is none
#   6. builds         the overview and cube plugins, the icon theme, the
#                     themes' wallpapers and sounds
#   7. services       the user services in packages/units.txt
#   8. smart extras   optional, a few GB: speech-to-text, the voices, the
#                     camera models (extras/setup-extras.sh; can run later)
# Then log out and pick "Hyprland (uwsm-managed)" at the login screen (with
# greetd: just log in; F3 picks another session). The
# first login opens a short welcome (theme, screens, microphone, smart
# features; ~/.config/hypr/scripts/welcome.py shows it again any time). Your
# screens start at their preferred modes side by side; arrange them in
# Settings > Displays, then run ~/.config/hypr/scripts/monitors-capture.py
# once and they are remembered for this machine.
#
# To undo it: ./uninstall.sh (restores what step 3 backed up; --dry-run first).
set -uo pipefail

REPO=$(cd "$(dirname "$0")" && pwd)
DRY=0 YES=0
for arg in "$@"; do
    case $arg in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    *) sed -n '2,30p' "$0"; exit 2 ;;
    esac
done
HYPR="$HOME/.config/hypr/scripts"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$HOME/.local/share/atrium/backup-$STAMP"

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
    if (( YES )) || [[ ! -t 0 ]]; then
        printf '  %s %s %s\n' "$q" "$hint" "$def"
        [[ $def == y ]]
        return
    fi
    read -rp "  $q $hint " reply
    reply=${reply:-$def}
    [[ ${reply,,} == y* ]]
}
list() { grep -v '^\s*#' "$1" | sed 's/#.*//; s/\s*$//' | grep -v '^$'; }
warn() { printf '  %s! %s%s\n' "$yellow" "$*" "$off"; }

# The graphics cards' makers, one per line (nvidia / amd / intel), from the
# kernel's PCI vendor ids in sysfs: no lspci or driver needed, so it works
# before any package is in. A connector (card1-DP-1) is not a card.
gpu_vendors() {
    local card vendor
    for card in /sys/class/drm/card[0-9]*; do
        [[ ${card##*/} == *-* ]] && continue
        read -r vendor < "$card/device/vendor" 2>/dev/null || continue
        case $vendor in
        0x10de) echo nvidia ;;
        0x1002|0x1022) echo amd ;;
        0x8086) echo intel ;;
        esac
    done | sort -u
}

# -- before anything ---------------------------------------------------------
[[ $EUID -ne 0 ]] || { echo "Run this as yourself, not root: it asks for sudo where needed."; exit 1; }
if ! [[ -r /etc/fedora-release ]]; then
    echo "This desktop is made for Fedora (44 or newer); /etc/fedora-release is missing."
    ask "Go on anyway?" n || exit 1
elif (( $(rpm -E %fedora) < 44 )); then
    echo "Fedora $(rpm -E %fedora): the Lua config needs Hyprland 0.56, packaged for Fedora 44 and newer."
    ask "Go on anyway?" n || exit 1
fi
printf '%sAtrium%s from %s\n' "$bold" "$off" "$REPO"
(( DRY )) && note "(dry run: nothing is changed)"

step "1/8  repositories"
fedora=$(rpm -E %fedora)
if ! rpm -q rpmfusion-free-release >/dev/null 2>&1; then
    run sudo dnf install -y \
        "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$fedora.noarch.rpm" \
        "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$fedora.noarch.rpm"
fi
while read -r repo; do
    [[ $repo == copr:* ]] && run sudo dnf copr enable -y "${repo#copr:}"
done < <(list "$REPO/packages/repos.txt")

step "2/8  packages"
mapfile -t pkgs < <(list "$REPO/packages/dnf.txt")
run sudo dnf install -y --skip-unavailable "${pkgs[@]}"

# The graphics card. Only what this machine's cards need: the NVIDIA driver
# on an AMD laptop (or the reverse) is at best dead weight.
mapfile -t vendors < <(gpu_vendors)
note "graphics: ${vendors[*]:-no card found}"
for v in "${vendors[@]}"; do
    case $v in
    nvidia)
        # rpmfusion's driver, built for each kernel (akmod). The CUDA part
        # brings NVML (libnvidia-ml), which the bar, Railguard and the
        # recorder read; libva-nvidia-driver lets video players decode on it.
        if rpm -q akmod-nvidia >/dev/null 2>&1; then
            note "NVIDIA: the driver (akmod-nvidia) is installed already"
            run sudo dnf install -y --skip-unavailable xorg-x11-drv-nvidia-cuda libva-nvidia-driver
        elif note "NVIDIA: the proprietary driver is built for your kernel on first boot (a few minutes)." &&
             note "With Secure Boot on, it also needs a key enrolled: see rpmfusion.org/Howto/Secure Boot." &&
             ask "Install the NVIDIA driver (akmod-nvidia)?" y; then
            run sudo dnf install -y --skip-unavailable akmod-nvidia xorg-x11-drv-nvidia-cuda libva-nvidia-driver
        else
            warn "without it (nouveau): no hardware video encoding (recording uses the CPU),"
            warn "no GPU numbers in the bar, local AI models on the CPU only"
        fi ;;
    amd)
        # Fedora's mesa-va-drivers leaves H.264 / HEVC out; rpmfusion's
        # freeworld build has them, which the recorder (VAAPI) needs.
        note "AMD: video encoding through VA-API (mesa-va-drivers-freeworld from rpmfusion)."
        if rpm -q mesa-va-drivers-freeworld >/dev/null 2>&1; then
            note "mesa-va-drivers-freeworld is installed already"
        elif rpm -q mesa-va-drivers >/dev/null 2>&1; then
            run sudo dnf swap -y mesa-va-drivers mesa-va-drivers-freeworld
        else
            run sudo dnf install -y --skip-unavailable mesa-va-drivers-freeworld
        fi
        run sudo dnf install -y --skip-unavailable libva-utils ;;
    intel)
        note "Intel: video encoding through VA-API (intel-media-driver; libva-intel-driver for older chips)."
        run sudo dnf install -y --skip-unavailable intel-media-driver libva-intel-driver libva-utils ;;
    esac
done
if (( ${#vendors[@]} == 0 )); then
    warn "No graphics card was found. The desktop works; what changes without one:"
    warn "  screen recording and instant replay encode on the CPU (x264, 30 fps)"
    warn "  the bar's GPU pill is hidden and Railguard does not watch GPU memory"
    warn "  local AI models (LM Studio) and voice typing run on the CPU: slowly"
elif [[ " ${vendors[*]} " != *" nvidia "* && " ${vendors[*]} " != *" amd "* ]]; then
    note "An Intel graphics chip only: local AI models run in RAM, slowly -- pick small ones."
fi

step "3/8  your config"
mapfile -t paths < <(cd "$REPO/home" && ls -d .config/* .local/share/fonts 2>/dev/null)
backed=0
for p in "${paths[@]}"; do
    [[ -e $HOME/$p ]] || continue
    # Only what this install would change: what is already identical to the
    # repo's (a second run) is not backed up again.
    if [[ -d $HOME/$p ]]; then
        [[ -z $(rsync -anc --out-format='%n' "$REPO/home/$p/" "$HOME/$p/" 2>/dev/null | grep -v '/$') ]] && continue
    else
        cmp -s "$REPO/home/$p" "$HOME/$p" && continue
    fi
    run mkdir -p "$BACKUP/$(dirname "$p")"
    run cp -a "$HOME/$p" "$BACKUP/$p"
    backed=1
done
(( backed )) && note "your previous files are in $BACKUP"
run rsync -a "$REPO/home/" "$HOME/"
# The few files that need an absolute path carry @HOME@ in the repo.
(( DRY )) || grep -rlF '@HOME@' "$HOME/.config/qt5ct" "$HOME/.config/qt6ct" 2>/dev/null |
    xargs -r sed -i "s|@HOME@|$HOME|g"
run mkdir -p "$HOME/.config/hypr/lua/hosts" "$HOME/Pictures/Screenshots" "$HOME/Pictures/Wallpapers"
run fc-cache -f "$HOME/.local/share/fonts"

step "4/8  your folders"
conf="$HOME/.config/hypr/desktop.conf"
if [[ -f $conf ]]; then
    note "$conf exists: kept as it is"
else
    projects=""
    for guess in "$HOME/Projects" "$HOME/projects" "$HOME/Github" "$HOME/GitHub" "$HOME/src" "$HOME/code"; do
        [[ -d $guess ]] && { projects=$guess; break; }
    done
    projects=${projects:-$HOME/Projects}
    if (( ! YES )) && [[ -t 0 ]]; then
        read -rp "  Where do your projects (git repos) live? [${projects/#$HOME/\~}] " reply
        [[ -n $reply ]] && projects=${reply/#\~/$HOME}
    fi
    note "projects folder: ${projects/#$HOME/\~} (Settings can change it)"
    if (( ! DRY )); then
        {
            echo "# Your folders (scripts read them through desktop_conf.py; Settings writes this)."
            echo "projects=${projects/#$HOME/\~}"
            echo "dotfiles="
        } > "$conf"
    fi
fi

step "5/8  system side"
if ask "Automatic snapshots of the system before every update (snapper, btrfs), and the phone link (KDE Connect)?" y; then
    run sudo "$HYPR/setup-root.sh"
fi
if [[ -e /sys/class/powercap/intel-rapl:0/energy_uj ]] && ask "Show the CPU's power draw in the bar (a tiny root service, cpu-power)?" y; then
    run sudo "$REPO/system/cpu-power/install.sh"
fi
if systemctl is-enabled -q display-manager.service 2>/dev/null; then
    note "login screen: $(systemctl show -p Id --value display-manager.service) (kept;"
    note "  sudo $REPO/system/greetd/install.sh --replace switches to greetd + tuigreet)"
elif ask "There is no login screen: use greetd + tuigreet (logs in to Hyprland)?" y; then
    run sudo "$REPO/system/greetd/install.sh"
fi
if ask "Let Alt+SysRq+F end a runaway process when the desktop is frozen (railguard)?" y; then
    run sudo "$REPO/system/railguard/install.sh"
fi

step "6/8  builds"
run "$HYPR/hyprview-build.sh"
run "$HYPR/hypr-cube-build.sh"
run python3 "$HYPR/make-icon-theme.py" --all
for maker in make-aero-wallpaper make-win95-wallpaper make-matrix-wallpaper make-moe-wallpaper \
             make-lofi-wallpaper make-luna-wallpaper make-seasons-wallpaper \
             make-orchard-wallpaper; do
    run python3 "$HYPR/$maker.py" --all
done
# orbit's are NASA / Webb photographs: downloaded (about 45 MB, hash-checked),
# so asked, not assumed -- without them `theme.py check orbit` says to run it.
if ask "Download the orbit theme's space photographs (about 45 MB)?" y; then
    run python3 "$HYPR/make-orbit-wallpaper.py" --all
fi
if ask "Render the moving wallpapers too (a few minutes)?" n; then
    run python3 "$HYPR/make-matrix-rain.py" --all
    run python3 "$HYPR/make-moe-sakura.py" --all
fi
run python3 "$HYPR/make-theme-sounds.py"

step "7/8  services"
run systemctl --user daemon-reload
while read -r unit; do
    run systemctl --user enable "$unit"
done < <(list "$REPO/packages/units.txt")

step "8/8  smart extras"
note "Speech-to-text (voice typing, captions), spoken replies and the camera features"
note "need models and Python packages (2-5 GB). Everything else works without them."
if ask "Set them up now? (extras/setup-extras.sh can do it later)" n; then
    run "$REPO/extras/setup-extras.sh"
fi
note "Local AI models: install LM Studio (lmstudio.ai), then pick models in Settings > AI & models."
if ! [[ -x $HOME/.lmstudio/bin/lms ]] && ! command -v lms >/dev/null 2>&1; then
    warn "LM Studio is not installed. Until it is, the assistant, voice commands, asking about"
    warn "the screen and the written summaries (daily brief, journal) do not answer; the rest"
    warn "of the desktop (and voice typing, spoken replies, the camera features) works without it."
fi

printf '\n%sDone.%s Log out and choose "Hyprland (uwsm-managed)" at the login screen.\n' "$bold" "$off"
note "The first login opens a short welcome: theme, screens, microphone, smart features."
note "Settings: SUPER+I (or the bar's gear). The smart features: Settings > Smart desktop."
note "Changed your mind? ./uninstall.sh --dry-run shows what it would put back."
