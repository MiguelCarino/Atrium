#!/usr/bin/env bash
# Maintainer side: copy the desktop from a running install ($HOME) into this
# repo, mirroring its place under $HOME (home/.config/hypr here is
# ~/.config/hypr). New users never run this -- they run ./install.sh.
#
#   ./sync.sh             home -> repo, then show what changed (staged)
#   ./sync.sh --commit    same, run the tests, commit and push if anything changed
#   ./sync.sh --check     read-only: how far home and the repo have drifted, as
#                         one JSON line (same shape as a dotfiles sync.sh --check)
#
# Only the desktop is taken. What belongs to ONE person -- this machine's
# screens, their projects, their work hours, their wallpapers, their own
# services -- is in PERSONAL below and never lands here; keep it in your own
# dotfiles repo instead (desktop.conf's dotfiles= names it).
#
# Enabled units are not copied as the *.wants/ symlinks (they point into the
# maintainer's home); the names go to packages/units.txt, which install.sh
# enables.
set -euo pipefail

REPO=$(cd "$(dirname "$0")" && pwd)
DEST=$REPO/home

PATHS=(
    .config/hypr/
    .config/waybar/
    .config/mako/
    .config/wofi/
    .config/themes/             # desktop themes (scripts/theme.py)
    .config/uwsm/
    .config/autostart/          # NotShowIn=Hyprland overrides of /etc/xdg/autostart
    .config/systemd/user/
    .config/qt5ct/              # the themes write their colours here
    .config/qt6ct/
    .config/kdeglobals
    .config/cliphist/
    .local/share/fonts/         # the themes' fonts
    .local/share/nautilus-python/extensions/atrium_files.py   # Files: right-click items, Git column (only ours: other extensions there stay yours)
    .config/fontconfig/conf.d/60-w95fa-pixels.conf
    .config/fontconfig/conf.d/60-inter-family.conf
)

# One person's, not the desktop's. rsync anchors a leading / to each
# transfer's root (the inside of .config/hypr/, say).
PERSONAL=(
    '--exclude=/lua/hosts/*.lua'        # this machine's screens (monitors-capture.py writes it)
    '--exclude=/contexts.json'          # their projects
    '--exclude=/desktop.conf'           # their folders
    '--exclude=/workhours.conf*'        # their employer's hours (.off: switched off)
    '--exclude=/emergency.conf'         # where they live (alerts)
    '--exclude=/region.conf'            # their weather place, clock
    '--exclude=/folder-access.json'     # which folders they let the AI read
    '--exclude=/scripts/dotfiles-backup.sh'
    '--exclude=dotfiles-backup.*'
    '--exclude=carino-traffic.*'
    '--exclude=*.wants/'                # see packages/units.txt
    '--exclude=/lmstudio.service.d/'    # this machine's LLM limits (llm-limits.py writes them)
    '--exclude=/agents.slice.d/'        # this machine's memory limits (railguard.py writes them)
    '--exclude=/heavy.slice.d/'
    # Not ours to publish: a patch to hypr-cube, which has no licence yet
    # (all rights reserved). The build works without it (plain upstream).
    '--exclude=/scripts/hypr-cube.patch'
)

# Generated or rebuildable (install.sh renders them).
EXCLUDES=(
    '--exclude=__pycache__/'
    '--exclude=*.pyc'
    '--exclude=.uuid'                   # fontconfig's per-machine folder ids
    '--exclude=/generated/'
    '--exclude=aero-*.png'
    '--exclude=win95-clouds-*.png'
    '--exclude=matrix-*.png'
    '--exclude=matrix-rain.mp4'
    '--exclude=moe-*.png'
    '--exclude=moe-sakura.mp4'
    '--exclude=/broken-*/'
    '--exclude=*.bak'
)

# The user units enabled on this install, minus the personal ones and the
# ones that ship OFF however the maintainer runs them (dock: the dock or
# taskbar is chosen in Settings): what install.sh turns on for a new user.
write_units() {
    local wants=$HOME/.config/systemd/user
    find "$wants" -mindepth 2 -maxdepth 2 -path '*.wants/*' -printf '%f\n' |
        grep -vE '^(dotfiles-backup|carino-traffic|dock)\.' | sort -u > "$REPO/packages/units.txt.new"
    {
        echo "# User units install.sh enables (sync.sh writes this from the maintainer's"
        echo "# install). Features that ship OFF are not here; Settings turns them on."
        cat "$REPO/packages/units.txt.new"
    } > "$REPO/packages/units.txt"
    rm -f "$REPO/packages/units.txt.new"
}

case ${1:-} in
--check)
    drift=0 sample=()
    for p in "${PATHS[@]}"; do
        [[ -e $HOME/$p ]] || continue
        while IFS= read -r line; do
            [[ -z $line || $line == */ ]] && continue
            drift=$((drift + 1))
            if [[ $p == */ ]]; then f="${p%/}/${line#./}"; else f=$p; fi
            ((${#sample[@]} < 12)) && sample+=("$f")
        done < <(rsync -an --delete --out-format='%n' "${PERSONAL[@]}" "${EXCLUDES[@]}" "$HOME/$p" "$DEST/$p" 2>/dev/null |
                 grep -v '^deleting .*/$')
    done
    cd "$REPO"
    uncommitted=$(git status --porcelain 2>/dev/null | wc -l)
    unpushed=$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)
    printf '{"drift": %d, "uncommitted": %d, "unpushed": %d, "sample": [' "$drift" "$uncommitted" "$unpushed"
    first=1
    for f in "${sample[@]}"; do
        ((first)) || printf ', '
        first=0
        printf '"%s"' "$(printf '%s' "$f" | sed 's/\\/\\\\/g; s/"/\\"/g')"
    done
    printf ']}\n'
    exit 0
    ;;
""|--commit) ;;
*) sed -n '2,10p' "$0"; exit 2 ;;
esac

for p in "${PATHS[@]}"; do
    if [[ ! -e $HOME/$p ]]; then
        echo "skip (missing): ~/$p" >&2
        continue
    fi
    mkdir -p "$DEST/$(dirname "$p")"
    # --delete-excluded: a file newly marked personal leaves the repo too
    rsync -a --delete --delete-excluded "${PERSONAL[@]}" "${EXCLUDES[@]}" "$HOME/$p" "$DEST/$p"
done
write_units
# wofi's @import must be absolute (GTK gets the text, not the path), so the
# live file names this home; theme.py's fix_wofi_import() points it at the
# new user's home on their first theme apply.
sed -i "s|file://$HOME/|file://~/|" "$DEST/.config/wofi/style.css"
# Files that can only hold an absolute path get @HOME@; install.sh writes the
# new user's home in its place.
sed -i "s|$HOME/|@HOME@/|g" "$DEST/.config/qt5ct/qt5ct.conf" "$DEST/.config/qt6ct/qt6ct.conf"
# The screen the bar, notifications and lock-screen widgets sit on is stored
# by name (Settings moves it); a new machine has other names, so the repo's
# copies name none: the bar on every screen, notifications on the focused
# one, the lock screen's widgets on all. `screens.py check` lists them.
sed -i '/^\s*"output": "[^"]*",\?\s*$/d' "$DEST/.config/waybar/config" "$DEST/.config/waybar/config-toolbox"
sed -i '/^output=/d' "$DEST/.config/mako/config"
sed -i 's/^\(\s*monitor\s*=\).*/\1/' "$DEST/.config/hypr/hyprlock.conf"

# Nothing personal may leave: the home path, the maintainer's name and email
# (git config) and the words in .personal-words (one per line, not committed:
# a surname, an employer, a project) are a hard stop, not a warning.
patterns=("$HOME/" "/home/$USER/")
for key in user.name user.email; do
    v=$(git config "$key" 2>/dev/null || true)
    [[ -n $v ]] && patterns+=("$v")
done
words=()     # whole words, any case: "Eden" must not trip on "credentials"
if [[ -f $REPO/.personal-words ]]; then
    while IFS= read -r w; do
        [[ -n $w && $w != \#* ]] && words+=("$w")
    done < "$REPO/.personal-words"
fi
for pat in "${patterns[@]}" "${words[@]/#/-w:}"; do
    flags=-rIliF
    [[ $pat == -w:* ]] && { flags=-rIliwF; pat=${pat#-w:}; }
    if hits=$(grep "$flags" -- "$pat" "$DEST" 2>/dev/null) && [[ -n $hits ]]; then
        echo "sync.sh: personal value \"$pat\" in:" >&2
        echo "$hits" | sed 's/^/  /' >&2
        exit 1
    fi
done

cd "$REPO"
git add -A home packages system extras install.sh sync.sh README.md LICENSE .gitignore
if git diff --cached --quiet; then
    echo "No changes."
    exit 0
fi
git diff --cached --stat | tail -15
if [[ ${1:-} == --commit ]]; then
    "$HOME/.config/hypr/tests/run.sh" || { echo "sync.sh: tests failed, not committing" >&2; exit 1; }
    git commit -q -m "sync $(date +%Y-%m-%d)"
    git push -q
    echo "Committed and pushed."
else
    echo "Staged. Run ./sync.sh --commit to commit and push."
fi
