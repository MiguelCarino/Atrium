#!/bin/bash
# Pending dnf + flatpak updates for waybar (custom/updates). The left click runs
# safe-upgrade.sh (btrfs snapshot, dnf, NVIDIA module check, flatpak, fwupd).
# Replaces the old inline exec, which had an unbalanced paren and so never ran:
#   "(dnf check-update -q|grep -c ^[a-z0-9]"
#
# The icon is emitted here as Pango markup, not in the module's "format":
#   - it is a package box (FA6 Solid box-open, U+F49E), NOT a cloud. The old
#     cloud-arrow-down sat right next to the weather pill's cloud glyphs and the
#     two pills read as one weather readout.
#   - the script decides its colour per state: neon magenta while updates are
#     pending, uncoloured otherwise so the CSS state colour (@dim when up to
#     date, @warn-fg on the yellow "many" wash) applies to the whole pill.
# The count itself is set in tabular figures by style.css (#custom-updates),
# the same readout face as the clock and the weather temperature beside it.
#
# Glyphs are written as \uXXXX JSON escapes (decoded by waybar's JSON parser),
# never as literal PUA characters that editors and diff tools mangle. They go
# through printf's %s, which does NOT interpret \u -- only the format string
# would.
#
# Classes: updated (0 pending), pending (1-49), many (50+), error (dnf failed
# or timed out, another check held the lock for over 180 s, or the script was
# run as root). Waybar's "signal": 8 re-runs it.

icon='\uf49e'          # box-open
# theme_color <key> <fallback> <var>: a colour from the desktop theme
# (theme.conf color.<key> -> ~/.config/waybar/generated/colors.conf, written by
# ~/.config/hypr/scripts/theme.py; themecolors.py documents it), into var.
# Builtins only -- no fork -- run once per check.
# A missing file or key leaves the fallback (cyberpunk's colour).
THEME_COLORS=$HOME/.config/waybar/generated/colors.conf
theme_color() {
    local k v
    printf -v "$3" '%s' "$2"
    [[ -r $THEME_COLORS ]] || return 0
    while IFS='=' read -r k v; do
        [[ $k == "$1" && $v =~ ^#[0-9a-fA-F]{6}$ ]] && printf -v "$3" '%s' "$v"
    done < "$THEME_COLORS"
}
theme_color pending '#ff2a6d' pending_col
icon_pending="<span color='${pending_col}'>${icon}</span>"   # @magenta, or the theme's color.pending

emit() {   # emit TEXT TOOLTIP CLASS   (tooltip must already be JSON-escaped)
    printf '{"text":"%s","tooltip":"%s","class":"%s"}\n' "$1" "$2" "$3"
}

# Never check as root: dnf would write root-owned files into the system cache
# and a waybar exec has no business holding root. As the user, dnf5 keeps its
# own metadata cache under ~/.cache/libdnf5, so nothing here needs sudo.
if ((EUID == 0)); then
    emit "$icon" "updates.sh refuses to run as root" error
    exit 0
fi

# One check at a time: the hourly interval and a SIGRTMIN+8 (right-click, or
# the post-upgrade refresh) can overlap, and two dnf processes would contend
# for the same cache lock. Waiting (bounded) instead of bailing, because an
# exec that prints nothing blanks the pill until the next run.
lock="${XDG_RUNTIME_DIR:-/tmp}/waybar-updates.lock"
exec 9>"$lock"
flock -w 180 9 || { emit "$icon" "Update check already running" error; exit 0; }

# Bounded and polite: a metadata refresh on a slow mirror must not hang the
# module forever (timeout -> exit 124), and it should not compete with games
# for CPU/IO (nice + idle IO class).
# dnf check-update exits 100 when updates exist, 0 when none do and 1 on
# error, so the status is read deliberately rather than tripping on `set -e`.
out=$(timeout 150 nice -n 19 ionice -c 3 dnf check-update -q 2>/dev/null)
rc=$?

# Flatpaks too: the left click (safe-upgrade.sh) updates them in the same run,
# so the count should include them. Read from the remotes' cached metadata;
# a failure just counts as none rather than failing the whole pill.
flatpaks=$(timeout 60 nice -n 19 flatpak remote-ls --updates --columns=application 2>/dev/null)
fcount=$(printf '%s' "$flatpaks" | grep -c .)

# The updates panel (updates_panel.py) reads the last check from here instead
# of running dnf itself: tab-separated, one record per line --
#     checked <epoch>      status ok|timeout|error <rc>
#     pkg <name.arch> <version>      flatpak <app id>
# Written on every check, whatever the outcome, atomically (tmp + mv).
cache="${XDG_RUNTIME_DIR:-/tmp}/waybar-updates.tsv"
{
    printf 'checked\t%s\n' "$EPOCHSECONDS"
    case $rc in
        0|100) printf 'status\tok\n' ;;
        124)   printf 'status\ttimeout\n' ;;
        *)     printf 'status\terror\t%s\n' "$rc" ;;
    esac
    printf '%s\n' "$out" | awk '/^Obsoleting/ { exit } /^[a-zA-Z0-9]/ && NF >= 2 { printf "pkg\t%s\t%s\n", $1, $2 }'
    printf '%s\n' "$flatpaks" | awk 'NF { printf "flatpak\t%s\n", $1 }'
} > "$cache.tmp" && mv -f "$cache.tmp" "$cache"

case $rc in
    0)   if ((fcount == 0)); then emit "$icon" "System is up to date" updated; exit 0; fi ;;
    100) ;;
    124) emit "$icon" "dnf check-update timed out (mirrors slow?)" error; exit 0 ;;
    *)   emit "$icon" "dnf check-update failed (exit $rc)" error; exit 0 ;;
esac

# Package lines only, and only from the upgrade list: stop at the "Obsoleting
# packages" section (dnf5-check-upgrade(8)). Its package lines repeat packages
# already in the upgrade list (an obsoleter is itself an upgrade), so counting
# them would count those twice; the indented obsoleted entries go with it.
# Blank lines are dropped by the ^[a-zA-Z0-9] filter.
# NF >= 2: dnf5 also prints a bare "Upgrades" section header, which matched
# the package-line pattern and was counted as an update of its own.
list=$(printf '%s\n' "$out" | awk '/^Obsoleting/ { exit } /^[a-zA-Z0-9]/ && NF >= 2')
count=$(printf '%s' "$list" | grep -c . )

if ((count + fcount == 0)); then
    emit "$icon" "System is up to date" updated
    exit 0
fi

tooltip=$(printf '%d package update(s)\n\n%s' "$count" \
    "$(printf '%s\n' "$list" | awk '{printf "  %s  →  %s\n", $1, $2}' | head -40)")
((count > 40)) && tooltip+=$'\n'"  … and $((count - 40)) more"
# A kernel in the list is the update that can leave NVIDIA without a module;
# safe-upgrade.sh checks for exactly that, so say it will -- only where the
# NVIDIA driver is loaded (any other GPU has nothing to check).
if [[ -d /sys/module/nvidia ]] && printf '%s\n' "$list" | grep -q '^kernel-core'; then
    tooltip+=$'\n\n'"Includes a new kernel: the NVIDIA module is built and checked before you reboot."
fi
if ((fcount)); then
    tooltip+=$'\n\n'"$fcount flatpak update(s)"$'\n'"$(printf '%s\n' "$flatpaks" | head -15 | sed 's/^/  /')"
fi
# No click hints: custom/updates has "tooltip": false (its panel is the
# long form); the tooltip text stays for `updates.sh` run by hand.
count=$((count + fcount))

# Tooltips are Pango markup too: escape &, < and > before the JSON escaping.
tooltip=${tooltip//&/"&amp;"}   # quoted: bash 5.2 patsub_replacement makes a bare & mean "the match"
tooltip=${tooltip//</"&lt;"}
tooltip=${tooltip//>/"&gt;"}
tooltip=${tooltip//\\/\\\\}
tooltip=${tooltip//\"/\\\"}
tooltip=${tooltip//$'\n'/\\n}

class=pending
((count >= 50)) && class=many

# On the yellow "many" wash a magenta glyph clashes; let it take @warn-fg.
if [[ $class == many ]]; then
    emit "$icon $count" "$tooltip" "$class"
else
    emit "$icon_pending $count" "$tooltip" "$class"
fi
