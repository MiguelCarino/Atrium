#!/usr/bin/env bash
# Atrium: the setup for a new user. Fedora 44 or newer (45, rawhide), a
# regular edition (Workstation, KDE Plasma, COSMIC, Everything / minimal: not
# an atomic one, Silverblue / Kinoite), an ordinary user account that may use
# sudo, then
#
#   git clone https://github.com/MiguelCarino/Atrium ~/Atrium && ~/Atrium/install.sh
#
#   ./install.sh             asks before each step that is optional
#   ./install.sh --yes       takes every default answer without asking
#   ./install.sh --dry-run   only prints what it would do
#   --replace-desktop        the default answer to "remove the other desktop?"
#                            becomes yes (so with --yes it is removed)
#   --keep-desktop           never offers to remove it
#
# Removing the desktop that was here is opt-in: its default answer is no,
# so `--yes` alone KEEPS it; only --replace-desktop (with --yes, or answered
# yes when asked) removes it. SimpleSetup's "carino-hyprland" choice passes
# --replace-desktop and still asks.
#
# Steps, each safe to run again:
#   0. tools          rsync, git, curl, python3, the dnf copr plugin, when missing
#   1. repositories   rpmfusion free + nonfree, the coprs in packages/repos.txt;
#                     stops here when no Hyprland 0.56+ can be installed
#   2. packages       Fedora's ffmpeg-free swapped for rpmfusion's ffmpeg (they
#                     conflict), packages/dnf.txt (names a release lacks are skipped),
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
#   5. system side    optional: btrfs snapshots around every update (snapper;
#                     only when / is btrfs)
#                     and the phone link's firewall ports (KDE Connect);
#                     the CPU power reading for the bar (cpu-power); the
#                     SysRq keys that end a freeze without a reset (railguard);
#                     a login screen (greetd + tuigreet) when there is none;
#                     and, asked (default no; --replace-desktop: yes), removing
#                     the desktop that was here (GNOME, KDE Plasma, COSMIC,
#                     Xfce, ...) after a preview, greetd replacing its login
#                     screen: a Hyprland-only machine. From a running session
#                     that removal is done at the next reboot.
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
DRY=0 YES=0 REPLACE_DEFAULT=n
for arg in "$@"; do
    case $arg in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --replace-desktop) REPLACE_DEFAULT=y ;;
    --keep-desktop) REPLACE_DEFAULT=keep ;;
    *) sed -n '/^set -uo/q;2,$p' "$0"; exit 2 ;;
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

# -- the other desktop (step 5) ----------------------------------------------
# dnf's group ids of the desktops Fedora ships: the desktop and its own apps
# only. Never an environment as a whole: Workstation's or KDE's also holds
# the core, hardware-support (firmware), multimedia and fonts groups.
DE_GROUPS='^(gnome-desktop|kde-desktop|kde-mobile|kde-apps|kde-media|kde-pim|kde-office|kde-education|kde-software-development|kde-spin-initial-setup|cosmic-desktop|cosmic-desktop-apps|xfce-desktop|xfce-apps|xfce-extra-plugins|xfce-media|xfce-office|lxqt-desktop|lxqt-apps|lxqt-l10n|lxqt-media|lxqt-office|lxde-desktop|lxde-apps|lxde-media|lxde-office|cinnamon-desktop|mate-desktop|mate-applications|mate-compiz|budgie-desktop|budgie-desktop-apps|deepin-desktop|deepin-desktop-apps|sugar-desktop|i3|sway|miracle-wm)$'
# Their sessions and login screens, removed by name too: a group removal
# keeps what another package still needs (gdm needs gnome-shell, ...).
DE_PACKAGES=(gnome-shell gnome-session gnome-session-wayland-session gnome-initial-setup gdm mutter
             plasma-workspace plasma-desktop plasma-login-manager sddm kwin
             cosmic-session cosmic-comp cosmic-greeter cosmic-panel cosmic-initial-setup
             xfce4-session xfwm4 lxqt-session cinnamon muffin mate-session-manager marco
             budgie-desktop lightdm)
# Never removed with it: marked as installed by you beforehand (together
# with every package in packages/dnf.txt), and the removal is refused if its
# preview still lists one. Names, and a pattern for the families.
PROTECT=(sudo polkit firewalld xdg-desktop-portal xdg-desktop-portal-gtk xdg-desktop-portal-hyprland
         gvfs gvfs-mtp gvfs-smb gvfs-gphoto2 gvfs-fuse gnome-keyring gnome-keyring-pam
         xdg-user-dirs xdg-utils adwaita-icon-theme hicolor-icon-theme dejavu-sans-fonts
         dejavu-sans-mono-fonts google-noto-sans-fonts google-noto-color-emoji-fonts
         default-fonts-core-sans mesa-dri-drivers mesa-vulkan-drivers akmod-nvidia
         xorg-x11-drv-nvidia xorg-x11-drv-nvidia-cuda mesa-va-drivers-freeworld intel-media-driver
         libva-nvidia-driver flatpak fwupd plymouth firefox nautilus kitty greetd tuigreet
         hyprland hyprland-uwsm uwsm openssh-server openssh-clients)
PROTECT_RX='^(kernel(-.+)?|linux-firmware(-.+)?|.+-firmware|microcode_ctl|grub2-.+|shim-.+|efibootmgr|mokutil|dracut(-.+)?|lvm2(-.+)?|cryptsetup(-.+)?|mdadm|device-mapper(-.+)?|btrfs-progs|e2fsprogs(-.+)?|xfsprogs|dosfstools|systemd(-.+)?|glibc(-.+)?|dnf5?(-.+)?|libdnf5?(-.+)?|rpm(-.+)?|NetworkManager(-wifi|-bluetooth|-wwan|-openvpn|-libnm|-ppp)?|ModemManager|wpa_supplicant|iw|selinux-policy(-.+)?|dbus(-.+)?|chrony|audit|fedora-release(-.+)?|fedora-repos(-.+)?|shadow-utils|util-linux(-.+)?|passwd|pipewire(-.+)?|wireplumber(-.+)?|bluez(-.+)?|alsa-ucm|alsa-utils)$'
REPLACED=0 OFFLINE=0

installed_desktops() {  # the desktops' group ids installed (@id), and their session packages
    { dnf -q group list --installed --hidden 2>/dev/null | awk '{print $1}' | grep -E "$DE_GROUPS" | sed 's/^/@/'
      local p
      for p in "${DE_PACKAGES[@]}"; do rpm -q "$p" >/dev/null 2>&1 && echo "$p"; done
    } | sort -u
}

remove_desktop() {  # remove_desktop <@group|package>...
    local keep=() p preview going hit=()
    for p in "${pkgs[@]}" "${PROTECT[@]}"; do rpm -q "$p" >/dev/null 2>&1 && keep+=("$p"); done
    mapfile -t -O "${#keep[@]}" keep < <(rpm -qa --qf '%{name}\n' | grep -E "$PROTECT_RX" | sort -u)
    run sudo dnf -q -y "${MARK[@]}" "${keep[@]}" ||
        { warn "could not mark what the desktop needs as yours: the old desktop is kept"; return 1; }
    note "marked ${#keep[@]} packages as yours (Atrium's, and the system's essentials)"
    if (( DRY )); then
        note "(the preview of what would be removed needs those marks; a real run shows it)"
        REPLACED=1
        return 0
    fi
    preview=$(sudo dnf remove --assumeno "$@" 2>&1)
    # Only the "Removing ..." sections: "Changing reason" lists packages too.
    going=$(awk '/^Removing/ {f = 1; next} /^[A-Z][^ ]/ {f = 0}
                 f && NF >= 4 && $2 ~ /^(x86_64|noarch|i686|aarch64)$/ {print $1}' <<<"$preview" | sort -u)
    if [[ -z $going ]]; then
        warn "dnf found nothing to remove for $*:"; tail -5 <<<"$preview" | sed 's/^/    /'
        return 1
    fi
    for p in "${PROTECT[@]}" "${pkgs[@]}"; do grep -qx -- "$p" <<<"$going" && hit+=("$p"); done
    mapfile -t -O "${#hit[@]}" hit < <(grep -E "$PROTECT_RX" <<<"$going")
    if (( ${#hit[@]} )); then
        warn "the removal would take ${hit[*]} too: refused, the old desktop is kept"
        return 1
    fi
    note "these $(wc -l <<<"$going") packages would be removed:"
    fmt -w 76 <<<"$(tr '\n' ' ' <<<"$going")" | sed 's/^/    /'
    ask "Remove them?" "$REPLACE_DEFAULT" || { note "kept"; return 1; }
    # Inside a graphical session the old login screen is running: removing it
    # live stops it (its package's scriptlet does), and the session and this
    # script with it. Then the removal waits for the next reboot.
    if systemctl is-active -q display-manager.service 2>/dev/null; then
        run sudo dnf remove -y --offline "$@" || return 1
        OFFLINE=1
    else
        run sudo dnf remove -y "$@" || return 1
    fi
    REPLACED=1
}

# -- before anything ---------------------------------------------------------
[[ $EUID -ne 0 ]] || { echo "Run this as yourself, not root: it asks for sudo where needed."; exit 1; }
# Atomic editions (Silverblue, Kinoite, COSMIC Atomic, ...) change their
# system with rpm-ostree, as a new image; dnf cannot install into it.
if [[ -e /run/ostree-booted ]]; then
    echo "This is an atomic Fedora (Silverblue, Kinoite, COSMIC Atomic...): its system is an"
    echo "image that rpm-ostree changes, and this desktop installs about 90 packages with dnf."
    echo "Use a regular edition instead (Workstation, KDE Plasma or COSMIC: fedoraproject.org)."
    exit 1
fi
command -v dnf >/dev/null 2>&1 && command -v rpm >/dev/null 2>&1 ||
    { echo "This desktop is made for Fedora (44 or newer) and installs with dnf, which is missing here."; exit 1; }
fedora=$(rpm -E %fedora)
if ! [[ -r /etc/fedora-release ]]; then
    echo "This desktop is made for Fedora (44 or newer); /etc/fedora-release is missing."
    ask "Go on anyway?" n || exit 1
elif ! [[ $fedora =~ ^[0-9]+$ ]] || (( fedora < 44 )); then
    # Hyprland 0.56+ (the Lua config) comes from the copr lionheartp/Hyprland,
    # which builds for Fedora 44, 45 and rawhide only; Fedora's own
    # repositories have no Hyprland at all.
    echo "Fedora $fedora: the desktop needs Hyprland 0.56 or newer, which is packaged (copr"
    echo "lionheartp/Hyprland) for Fedora 44 and newer only. Upgrade Fedora first, then run this again:"
    echo "  sudo dnf upgrade --refresh"
    echo "  sudo dnf system-upgrade download --releasever=44   (or a newer release)"
    echo "  sudo dnf offline reboot"
    exit 1
fi
rawhide=0
grep -qi rawhide /etc/fedora-release 2>/dev/null && rawhide=1
# dnf5 (Fedora 41 on) and dnf4 name the same things differently.
if dnf --version 2>/dev/null | grep -q dnf5; then
    SKIP=--skip-unavailable plugins=dnf5-plugins MARK=(mark user)
else
    SKIP=--setopt=strict=0 plugins=dnf-plugins-core MARK=(mark install)
fi
printf '%sAtrium%s from %s (Fedora %s%s)\n' "$bold" "$off" "$REPO" "$fedora" "$( ((rawhide)) && echo ', rawhide')"
(( DRY )) && note "(dry run: nothing is changed)"
if (( ! DRY )) && ! sudo -v; then
    echo "sudo is needed for the packages and the system side: this account may not use it."
    exit 1
fi
# The user services (step 7) need the session's runtime folder; from a
# `sudo -u` shell it is not in the environment, but it is there.
[[ -z ${XDG_RUNTIME_DIR:-} && -d /run/user/$UID ]] && export XDG_RUNTIME_DIR=/run/user/$UID

# The tools this script itself uses before step 2 brings the rest: a minimal
# install has neither rsync nor git, and `dnf copr` is a plugin.
tools=()
for pair in rsync:rsync git:git-core curl:curl python3:python3 cmp:diffutils fc-cache:fontconfig; do
    command -v "${pair%%:*}" >/dev/null 2>&1 || tools+=("${pair#*:}")
done
rpm -q "$plugins" >/dev/null 2>&1 || tools+=("$plugins")
if (( ${#tools[@]} )); then
    step "0/8  tools"
    run sudo dnf install -y "${tools[@]}" || { echo "Could not install ${tools[*]}: stopping."; exit 1; }
fi

step "1/8  repositories"
if ! rpm -q rpmfusion-free-release >/dev/null 2>&1; then
    # rawhide's release packages are named -rawhide, not by number; a
    # numbered release whose packages are not out yet tries those too.
    rf=https://mirrors.rpmfusion.org
    rel=$fedora; (( rawhide )) && rel=rawhide
    run sudo dnf install -y "$rf/free/fedora/rpmfusion-free-release-$rel.noarch.rpm" \
        "$rf/nonfree/fedora/rpmfusion-nonfree-release-$rel.noarch.rpm" ||
    run sudo dnf install -y "$rf/free/fedora/rpmfusion-free-release-rawhide.noarch.rpm" \
        "$rf/nonfree/fedora/rpmfusion-nonfree-release-rawhide.noarch.rpm" ||
    warn "rpmfusion is not set up: ffmpeg, the NVIDIA driver and the video-encoding drivers are skipped"
fi
while read -r repo; do
    [[ $repo == copr:* ]] && run sudo dnf copr enable -y "${repo#copr:}"
done < <(list "$REPO/packages/repos.txt")
# Without Hyprland there is no desktop: stop here rather than install the rest.
if (( ! DRY )); then
    hv=$(sudo dnf -q repoquery --latest-limit=1 --qf '%{version}\n' hyprland 2>/dev/null | tail -n1)
    if [[ -z $hv ]] || [[ $(printf '%s\n' 0.56 "$hv" | sort -V | head -n1) != 0.56 ]]; then
        echo "No Hyprland 0.56 or newer can be installed on Fedora $fedora (found: ${hv:-none})."
        echo "It comes from the copr lionheartp/Hyprland (packages/repos.txt): check that it has a"
        echo "build for this release (copr.fedorainfracloud.org/coprs/lionheartp/Hyprland)."
        exit 1
    fi
    note "Hyprland $hv"
fi

step "2/8  packages"
mapfile -t pkgs < <(list "$REPO/packages/dnf.txt")
# Every edition comes with Fedora's ffmpeg-free; rpmfusion's ffmpeg conflicts
# with it and dnf then refuses the whole list. rpmfusion's way is a swap.
if rpm -q ffmpeg-free >/dev/null 2>&1 && { (( DRY )) || rpm -q rpmfusion-free-release >/dev/null 2>&1; }; then
    run sudo dnf swap -y --allowerasing ffmpeg-free ffmpeg
fi
run sudo dnf install -y "$SKIP" "${pkgs[@]}" || {
    warn "the package list did not go in as a whole; again, leaving out what conflicts"
    run sudo dnf install -y "$SKIP" --skip-broken "${pkgs[@]}"
}
(( DRY )) || command -v Hyprland >/dev/null 2>&1 ||
    warn "Hyprland is not installed: the steps below go on, but there is no desktop to log in to"

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
            run sudo dnf install -y "$SKIP" xorg-x11-drv-nvidia-cuda libva-nvidia-driver
        elif note "NVIDIA: the proprietary driver is built for your kernel on first boot (a few minutes)." &&
             note "With Secure Boot on, it also needs a key enrolled: see rpmfusion.org/Howto/Secure Boot." &&
             ask "Install the NVIDIA driver (akmod-nvidia)?" y; then
            run sudo dnf install -y "$SKIP" akmod-nvidia xorg-x11-drv-nvidia-cuda libva-nvidia-driver
        else
            warn "without it (nouveau): no hardware video encoding (recording uses the CPU),"
            warn "no GPU numbers in the bar, local AI models on the CPU only"
        fi
        # A hybrid laptop's offload card (no screens of its own): powered
        # down while idle. The script checks for one and does nothing else.
        run sudo "$REPO/system/nvidia-power/install.sh" ;;
    amd)
        # Fedora's mesa-va-drivers leaves H.264 / HEVC out; rpmfusion's
        # freeworld build has them, which the recorder (VAAPI) needs.
        note "AMD: video encoding through VA-API (mesa-va-drivers-freeworld from rpmfusion)."
        if rpm -q mesa-va-drivers-freeworld >/dev/null 2>&1; then
            note "mesa-va-drivers-freeworld is installed already"
        elif rpm -q mesa-va-drivers >/dev/null 2>&1; then
            run sudo dnf swap -y mesa-va-drivers mesa-va-drivers-freeworld
        else
            run sudo dnf install -y "$SKIP" mesa-va-drivers-freeworld
        fi
        run sudo dnf install -y "$SKIP" libva-utils ;;
    intel)
        note "Intel: video encoding through VA-API (intel-media-driver; libva-intel-driver for older chips)."
        run sudo dnf install -y "$SKIP" intel-media-driver libva-intel-driver libva-utils ;;
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
mapfile -t paths < <(cd "$REPO/home" && ls -d .config/* .local/share/fonts .local/share/nautilus-python/extensions/* 2>/dev/null)
# ~/.config/autostart/*.desktop here only hide a system autostart entry from
# Hyprland (NotShowIn=Hyprland); one whose system entry is not on this
# machine would hide nothing, so it is not copied.
keep=()
for f in "$REPO"/home/.config/autostart/*.desktop; do
    f=${f##*/}
    [[ -e /etc/xdg/autostart/$f || -e $HOME/.config/autostart/$f ]] || keep+=("--exclude=/.config/autostart/$f")
done
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
run rsync -a "${keep[@]}" "$REPO/home/" "$HOME/"
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
# A laptop's I2C touchpad that the driver missed at boot (some firmware
# powers it up late) is bound again. The script checks for one and does
# nothing else.
run sudo "$REPO/system/touchpad-reprobe/install.sh"
# The desktop that was here (GNOME, Plasma, COSMIC, ...): offered for
# removal, so what is left is a Hyprland desktop and nothing else. Safe order:
# the desktop's packages are all in already (step 2); they and the system's
# essentials are marked as installed by you, so removing the other desktop
# cannot take them along as its dependencies; a preview shows what goes and
# is refused if it touches anything protected; greetd replaces the old login
# screen in the same run. From inside a graphical session the removal is
# an offline transaction (done at the next reboot): removing the running
# login screen live would stop it, and the session with it, mid-transaction.
mapfile -t envs < <(installed_desktops)
if (( ${#envs[@]} )) && [[ $REPLACE_DEFAULT != keep ]]; then
    note "another desktop is installed: ${envs[*]}"
    if ask "Remove it, so this is a Hyprland-only desktop (shows what goes first)?" "$REPLACE_DEFAULT"; then
        remove_desktop "${envs[@]}"
    else
        note "kept; Hyprland is one more session at its login screen"
    fi
fi
if (( REPLACED )); then
    run sudo "$REPO/system/greetd/install.sh" --replace
elif systemctl is-enabled -q display-manager.service 2>/dev/null; then
    note "login screen: $(systemctl show -p Id --value display-manager.service) (kept;"
    note "  sudo $REPO/system/greetd/install.sh --replace switches to greetd + tuigreet)"
elif ask "There is no login screen: use greetd + tuigreet (logs in to Hyprland)?" y; then
    run sudo "$REPO/system/greetd/install.sh"
fi
if (( ! DRY )) && { (( REPLACED )) || systemctl is-enabled -q greetd.service 2>/dev/null; }; then
    [[ $(systemctl get-default 2>/dev/null) == graphical.target ]] ||
        warn "the default boot target is $(systemctl get-default 2>/dev/null || echo unknown), not graphical.target: sudo systemctl set-default graphical.target"
    systemctl is-enabled -q greetd.service 2>/dev/null ||
        warn "greetd is not enabled: there would be no login screen. sudo $REPO/system/greetd/install.sh --replace"
fi
if ask "Let Alt+SysRq+F end a runaway process when the desktop is frozen (railguard)?" y; then
    run sudo "$REPO/system/railguard/install.sh"
fi

step "6/8  builds"
run "$HYPR/hyprview-build.sh"
run "$HYPR/hypr-cube-build.sh"
# The themes' icon sets are built from Papirus: packages/dnf.txt installs it
# (/usr/share/icons/Papirus); a copy of your own in ~/.local/share/icons is
# used first. Chicago95, candy-icons and Sweet-Rainbow (win95's and
# cyberpunk's designed bases) are optional and not packaged: without them
# those two trace every app from Papirus (see make-icon-theme.py).
if [[ -f $HOME/.local/share/icons/Papirus/index.theme || -f /usr/share/icons/Papirus/index.theme ]] || (( DRY )); then
    run python3 "$HYPR/make-icon-theme.py" --all
else
    warn "the themes' own icon sets are not built: Papirus is not installed"
    warn "(sudo dnf install papirus-icon-theme papirus-icon-theme-dark, then $HYPR/make-icon-theme.py --all);"
    warn "the themes use Adwaita's icons meanwhile"
fi
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
# `enable` only makes links, so it works without a running user session
# (a container, an ssh shell without one); the reload needs the session.
if systemctl --user show-environment >/dev/null 2>&1; then
    run systemctl --user daemon-reload
else
    note "no user session here: the services are enabled, and start at your next login"
fi
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

# Another desktop on this machine (GNOME, Plasma, COSMIC) shares some of
# what the themes set: say so once, here, rather than surprise anyone.
others=""
(( REPLACED )) || others=$(grep -lsiE '^DesktopNames=.*(GNOME|KDE|COSMIC)' /usr/share/wayland-sessions/*.desktop /usr/share/xsessions/*.desktop |
    xargs -r grep -hsi '^Name=' | sed 's/^Name=//' | sort -u | paste -sd, - | sed 's/,/, /g')
if [[ -n $others ]]; then
    warn "You also have: $others. Those sessions share some of what a theme here sets:"
    warn "  GTK's light/dark, icon and pointer themes and window buttons (gsettings),"
    warn "  ~/.config/gtk-4.0/gtk.css (GNOME apps' colours; yours kept as gtk.css.before-themes),"
    warn "  COSMIC's dark theme and COSMIC Terminal's colours (~/.config/cosmic; *.before-themes)."
fi

if (( OFFLINE )); then
    printf '\n%sDone.%s Reboot to finish: the old desktop is removed during the restart,\n' "$bold" "$off"
    note "then greetd's login screen starts Hyprland:  sudo dnf offline reboot"
elif (( REPLACED )); then
    printf '\n%sDone.%s Reboot: greetd (tuigreet) is the login screen and starts Hyprland.\n' "$bold" "$off"
else
    printf '\n%sDone.%s Log out and choose "Hyprland (uwsm-managed)" at the login screen.\n' "$bold" "$off"
fi
note "The first login opens a short welcome: theme, screens, microphone, smart features."
note "Settings: SUPER+I (or the bar's gear). The smart features: Settings > Smart desktop."
note "Changed your mind? ./uninstall.sh --dry-run shows what it would put back."
