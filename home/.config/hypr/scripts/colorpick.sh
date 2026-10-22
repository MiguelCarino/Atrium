#!/usr/bin/env bash
# Colour picker with a memory (SUPER+P).
#
#   colorpick.sh             pick with hyprpicker: hex onto the clipboard, a
#                            toast with a swatch of it, and into the history
#   colorpick.sh history     the remembered colours, newest first, one per line
#   colorpick.sh copy <hex>  put one back on the clipboard (the launcher's
#                            "#" mode does this when you pick from the history)
#   colorpick.sh clear       forget them all
#
# The history is a plain text file, newest first, no repeats, HISTORY_MAX
# long: ~/.local/share/colorpick/history. Plain text so the launcher, a shell
# and a quick `cat` all read it the same way.
#
# The toast carries a 64px swatch generated with ImageMagick into tmpfs; mako
# shows an image path in -i as the notification's icon. Each colour also comes
# with its rgb() and hsl() forms in the body, since the clipboard only takes
# one and the other two are what CSS work tends to want next.

set -u

HISTORY="${XDG_DATA_HOME:-$HOME/.local/share}/colorpick/history"
HISTORY_MAX=30
SWATCH_DIR="${XDG_RUNTIME_DIR:-/tmp}/colorpick"

notify() {  # notify <urgency> <icon> <summary> [body]
    notify-send -a "Colour picker" -u "$1" -i "$2" \
        -h string:x-canonical-private-synchronous:colorpick "$3" "${4:-}"
}

remember() {  # remember <#rrggbb>
    mkdir -p "$(dirname "$HISTORY")"
    { echo "$1"; grep -vix "$1" "$HISTORY" 2>/dev/null; } | head -n "$HISTORY_MAX" > "$HISTORY.tmp"
    mv "$HISTORY.tmp" "$HISTORY"
}

describe() {  # describe <#rrggbb> -> "rgb(...)  hsl(...)"
    local r=$((16#${1:1:2})) g=$((16#${1:3:2})) b=$((16#${1:5:2}))
    python3 -c "
import colorsys, sys
r, g, b = (int(x) / 255 for x in sys.argv[1:])
h, l, s = colorsys.rgb_to_hls(r, g, b)
print(f'rgb({sys.argv[1]}, {sys.argv[2]}, {sys.argv[3]})   hsl({h*360:.0f}, {s*100:.0f}%, {l*100:.0f}%)')
" "$r" "$g" "$b"
}

announce() {  # announce <#rrggbb> <summary>
    local swatch="$SWATCH_DIR/${1#\#}.png"
    mkdir -p "$SWATCH_DIR"
    [[ -s $swatch ]] || magick -size 64x64 xc:"$1" "$swatch" 2>/dev/null
    notify low "${swatch}" "$2 $1" "$(describe "$1")"
}

pick() {
    command -v hyprpicker >/dev/null || { notify critical dialog-error "hyprpicker is not installed" "sudo dnf install hyprpicker"; exit 1; }
    local hex
    # -l: lowercase, as the theme files write them. Escape prints nothing.
    hex=$(hyprpicker -f hex -l -q 2>/dev/null | tr -d '[:space:]')
    [[ $hex =~ ^#[0-9a-f]{6}$ ]] || exit 0
    printf '%s' "$hex" | wl-copy
    remember "$hex"
    announce "$hex" "Copied"
}

case "${1:-pick}" in
    pick)    pick ;;
    history) cat "$HISTORY" 2>/dev/null ;;
    copy)
        [[ ${2:-} =~ ^#[0-9a-fA-F]{6}$ ]] || { echo "usage: ${0##*/} copy #rrggbb" >&2; exit 2; }
        printf '%s' "${2,,}" | wl-copy
        remember "${2,,}"
        announce "${2,,}" "Copied" ;;
    clear)   rm -f "$HISTORY"; notify low color-select "Colour history cleared" ;;
    *)
        sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
        exit 2 ;;
esac
