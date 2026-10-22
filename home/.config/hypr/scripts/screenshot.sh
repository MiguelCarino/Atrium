#!/usr/bin/env bash
# Screenshots: hyprshot's picker with Settings' folder / format / copy, and
# the extras hyprshot does not do on its own.
#
#   screenshot.sh output|region|window
#                               the ALT+S family: hyprshot picks it, saved into
#                               the screenshot folder in the chosen format, and
#                               copied too unless that is switched off
#   screenshot.sh region-copy   region -> clipboard only, no file written
#   screenshot.sh annotate      region -> satty (draw/arrow/blur), saves into
#                               the screenshot folder (always PNG) and copies
#                               to the clipboard (Enter; only saves when
#                               "also copy" is off)
#   screenshot.sh ocr           region -> tesseract -> text on the clipboard
#   screenshot.sh pretty [region]
#                               the focused window (or a dragged region) with
#                               rounded corners and a soft shadow, on a padded
#                               gradient in the theme's accent -- ready for a
#                               README or a chat. Saved, and copied unless
#                               that is switched off.
#
# Bound in lua/binds.lua under the "Screenshots" section (SUPER+S,
# SUPER+SHIFT+S, SUPER+O, SUPER+CTRL+S). The plain monitor/region/window shots
# are ALT+S / ALT+SHIFT+S / ALT+CTRL+S; until those binds call
# `screenshot.sh output|region|window` they run hyprshot directly into
# lua/shared.lua's scrDir and ignore the folder / format / copy settings.
#
# WHY grim+slurp directly instead of hyprshot: hyprshot always either writes a
# file (-o) or copies (--clipboard-only), and has no "hand me the PNG on
# stdout" mode. We need the raw image for satty and tesseract, and hyprshot is
# itself just slurp + grim underneath, so calling them directly is the same
# capture with one fewer layer.
#
# Optional tools (satty, tesseract) are checked with command -v and a
# notification tells you the exact dnf command if one is missing -- a bind
# that silently does nothing is the worst failure mode for a keyboard
# shortcut, because you cannot tell "missing tool" from "key not bound".

set -u

# The folder, the format, whether a saved shot is also copied and the OCR
# languages are Settings > Screenshots & recording's (capture-settings.py,
# which keeps them in ~/.local/state/hypr/capture.conf), read here on every
# run so a change applies to the next shot. Deliberately NOT read from
# $XDG_SCREENSHOTS_DIR: Hyprland sets it for apps it launches, but shells that
# started elsewhere can carry a stale value (seen here: a literal "~/screens",
# which no program expands), and a bind must save to one predictable place.
# If capture-settings.py does not answer, the defaults below still work.
SCR_DIR="$HOME/Pictures/Screenshots"; FORMAT=png; COPY=on; OCR_LANGS=eng+spa
mapfile -t _cfg < <("$(dirname "$(readlink -f "$0")")/capture-settings.py" \
                    get shot_dir shot_format shot_copy ocr_langs 2>/dev/null)
if (( ${#_cfg[@]} == 4 )); then
    SCR_DIR=${_cfg[0]}; FORMAT=${_cfg[1]}; COPY=${_cfg[2]}; OCR_LANGS=${_cfg[3]}
fi
APP="Screenshot"     # notify-send app name, groups them in mako

# A PNG in, the file in the chosen format out. PNG is a plain copy; JPEG and
# WebP go through ImageMagick at a quality where text stays crisp. Without
# ImageMagick it stays PNG rather than failing the shot -- the notification
# names the file, so the extension says what you got.
save_as() {   # save_as <png> <path without extension> -> prints the file written
    local src=$1 base=$2
    if [[ $FORMAT != png ]] && command -v magick >/dev/null 2>&1; then
        local q=92; [[ $FORMAT == webp ]] && q=90
        if magick "$src" -quality "$q" "$base.$FORMAT" 2>/dev/null; then
            printf '%s' "$base.$FORMAT"
            return 0
        fi
    fi
    cp -- "$src" "$base.png" && printf '%s' "$base.png"
}

notify() {  # notify <urgency> <summary> [body]
    notify-send -a "$APP" -u "$1" "$2" "${3:-}"
}

# need <command> [dnf packages] [full hint] -> exits with a notification if
# missing. The hint defaults to "sudo dnf install <packages>"; the third
# argument replaces it for a tool that is not in any enabled repo (satty).
need() {
    command -v "$1" >/dev/null 2>&1 && return 0
    local hint="${3:-sudo dnf install ${2:-$1}}"
    notify critical "$1 is not installed" "$hint"
    echo "screenshot.sh: $1 is not installed: $hint" >&2
    exit 127
}

# satty is not packaged in fedora, updates, rpmfusion or the Hyprland copr.
# It is installed as the upstream release binary in ~/.local/bin (`gh release
# download -R Satty-org/Satty -p 'satty-x86_64-unknown-linux-gnu.tar.gz'`; it
# links against the system gtk4/libadwaita), or would come from `cargo install`
# into ~/.cargo/bin. Neither is on Hyprland's PATH (/usr/local/bin:/usr/bin),
# and binds inherit that PATH, so both are looked in here.
PATH="$PATH:$HOME/.local/bin:$HOME/.cargo/bin"

# Region picker. Prints "X,Y WxH" or exits quietly when you press Escape --
# cancelling is a normal action, not an error, so no notification for it.
pick_region() {
    # A second slurp on top of the first one stacks two overlays and the
    # second grabs input; a double key press would otherwise do that.
    if pgrep -x slurp >/dev/null; then exit 0; fi
    local geo
    geo="$(slurp -d)" || exit 0
    [ -n "$geo" ] || exit 0
    # Give slurp's layer surface one frame or two to unmap; without this the
    # selection border can land in the capture when layer animations are on.
    sleep 0.1
    printf '%s' "$geo"
}

# --- modes -------------------------------------------------------------------

# output | region | window through hyprshot, which does the picking (click a
# monitor or a window, drag a region) and hands the PNG over on stdout with
# --raw; saving and copying are done here so they follow the settings.
shot() {   # shot output|region|window
    need hyprshot; need grim; need slurp
    mkdir -p "$SCR_DIR"
    tmp="$(mktemp --suffix=.png "${XDG_RUNTIME_DIR:-/tmp}/shot-XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    # Escape in the picker: hyprshot exits without an image, which is a
    # cancel, not a failure -- so no notification for it.
    hyprshot -m "$1" --raw > "$tmp" 2>/dev/null
    [ -s "$tmp" ] || exit 0
    local out
    out="$(save_as "$tmp" "$SCR_DIR/$(date +%Y-%m-%d-%H%M%S)_$1")" || {
        notify critical "Screenshot not saved" "Could not write into $SCR_DIR"
        exit 1
    }
    if [[ $COPY == on ]] && command -v wl-copy >/dev/null 2>&1; then
        wl-copy --type image/png < "$tmp"
        notify low "Screenshot saved and copied" "$out"
    else
        notify low "Screenshot saved" "$out"
    fi
}

region_copy() {
    need grim; need slurp; need wl-copy wl-clipboard
    local geo
    geo="$(pick_region)" || exit 0
    [ -n "$geo" ] || exit 0
    # Pipe straight in: no temp file, nothing ends up on disk.
    if grim -g "$geo" - | wl-copy --type image/png; then
        notify low "Region copied" "Image is on the clipboard (not saved)"
    else
        notify critical "Screenshot failed" "grim could not capture $geo"
        exit 1
    fi
}

annotate() {
    need grim; need slurp; need wl-copy wl-clipboard
    # Checked before the picker so you are not asked to drag for nothing. Not
    # in any repo enabled here (see the PATH note above need), so the hint is
    # cargo; satty links against GTK4 and libadwaita, hence the -devel pair.
    need satty satty "not in Fedora repos: sudo dnf install gtk4-devel libadwaita-devel, then cargo install --locked satty"
    local geo
    geo="$(pick_region)" || exit 0
    [ -n "$geo" ] || exit 0
    mkdir -p "$SCR_DIR"

    # Capture to a temp file instead of piping: satty reads stdin fine, but a
    # file means a failed capture is caught here with a clear message instead
    # of satty opening on an empty image.
    # Global, not local: the EXIT trap fires after this function has
    # returned, when a local would already be gone (and set -u would abort).
    tmp="$(mktemp --suffix=.png "${XDG_RUNTIME_DIR:-/tmp}/satty-src-XXXXXX")"
    trap 'rm -f "$tmp"' EXIT
    if ! grim -g "$geo" "$tmp"; then
        notify critical "Screenshot failed" "grim could not capture $geo"
        exit 1
    fi

    # --output-filename takes strftime patterns, so every save gets its own
    # name next to hyprshot's shots. --copy-command makes satty's copy action
    # use wl-copy (its built-in clipboard needs the window to stay alive).
    local args=(--filename "$tmp"
                --output-filename "$SCR_DIR/%Y-%m-%d-%H%M%S_annotated.png"
                --copy-command wl-copy
                --early-exit)
    # Enter = save AND copy, which is what this bind promises. The flag only
    # exists in newer satty, and satty rejects unknown flags, so feature-test
    # it against --help instead of assuming the Fedora build has it. Without
    # it, Ctrl+S saves and Ctrl+C copies inside satty.
    # satty always writes PNG, whatever the format setting says. With
    # "also copy" switched off, Enter only saves (Ctrl+C still copies).
    if satty --help 2>/dev/null | grep -q -- '--actions-on-enter'; then
        if [[ $COPY == on ]]; then
            args+=(--actions-on-enter "save-to-clipboard,save-to-file")
        else
            args+=(--actions-on-enter "save-to-file")
        fi
    fi
    # Not exec: the EXIT trap has to run after satty closes to delete $tmp.
    satty "${args[@]}"
}

ocr() {
    need grim; need slurp; need wl-copy wl-clipboard
    # On Fedora the base package ships NO language data -- not even English:
    # tesseract neither requires nor recommends tesseract-langpack-eng. Without
    # eng in the hint, English text would be read with the Spanish model.
    need tesseract "tesseract tesseract-langpack-eng tesseract-langpack-spa"
    # The chosen languages (eng+spa unless changed), but only the ones
    # actually installed: tesseract errors out on a missing traineddata
    # instead of skipping it. Fedora ships each as tesseract-langpack-<lang>,
    # eng included.
    local have langs=""
    have="$(tesseract --list-langs 2>/dev/null | tail -n +2)"
    for l in ${OCR_LANGS//+/ }; do
        grep -qx "$l" <<<"$have" && langs="${langs:+$langs+}$l"
    done
    if [ -z "$langs" ]; then
        # None of the wanted languages: fall back to whatever is there (skipping
        # osd, which is script detection, not a language).
        langs="$(grep -vx osd <<<"$have" | head -n1)"
    fi
    if [ -z "$langs" ]; then
        notify critical "No tesseract language data" "sudo dnf install tesseract-langpack-eng tesseract-langpack-spa"
        exit 1
    fi

    local geo
    geo="$(pick_region)" || exit 0
    [ -n "$geo" ] || exit 0

    # -s 2 renders the region at twice the pixel density: tesseract is tuned
    # for ~300 dpi scans and misreads 1x UI text (small fonts, thin strokes)
    # far more than upscaled text. --psm 6 would force a single block; the
    # default auto layout copes better with mixed UI regions, so it stays.
    local text
    text="$(grim -s 2 -g "$geo" - | tesseract stdin stdout -l "$langs" 2>/dev/null)"
    # Trim trailing blank lines/form feeds tesseract appends.
    text="$(printf '%s' "$text" | sed -e 's/\f//g' | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}')"
    if [ -z "${text//[[:space:]]/}" ]; then
        notify normal "OCR: no text found" "Nothing recognised in the selection ($langs)"
        exit 0
    fi
    printf '%s' "$text" | wl-copy
    # Preview: whitespace collapsed to one line, cut at ~80 chars.
    local preview
    preview="$(printf '%s' "$text" | tr -s '[:space:]' ' ' | sed 's/^ //')"
    [ "${#preview}" -gt 80 ] && preview="${preview:0:80}..."
    notify low "OCR copied ($langs)" "$preview"
}

# The accent the bar is wearing (theme-from-wallpaper.py), else neon cyan.
accent() {
    local a
    a=$(sed -n 's/^accent=//p' "${XDG_STATE_HOME:-$HOME/.local/state}/hypr/display.conf" 2>/dev/null)
    [[ $a =~ ^#[0-9a-fA-F]{6}$ ]] && echo "$a" || echo "#00f0ff"
}

pretty() {
    need grim; need wl-copy wl-clipboard; need magick ImageMagick
    local geo
    if [[ ${1:-} == region ]]; then
        need slurp
        geo="$(pick_region)" || exit 0
    else
        # The focused window, from Hyprland: at/size are layout coordinates,
        # the same space grim -g takes. No window focused (an empty
        # workspace) falls back to dragging a region rather than doing nothing.
        geo=$(hyprctl activewindow -j 2>/dev/null |
              jq -r 'select(.at) | "\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"' 2>/dev/null)
        if [[ -z $geo ]]; then
            need slurp
            geo="$(pick_region)" || exit 0
        fi
    fi
    [ -n "$geo" ] || exit 0
    mkdir -p "$SCR_DIR"

    tmp="$(mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/pretty-XXXXXX")"
    trap 'rm -rf "$tmp"' EXIT
    if ! grim -g "$geo" "$tmp/shot.png"; then
        notify critical "Screenshot failed" "grim could not capture $geo"
        exit 1
    fi

    # Rounded corners (the classic ImageMagick mask: one corner drawn, then
    # flipped and flopped onto the other three), then a drop shadow, then the
    # whole thing centred on a diagonal gradient with PAD of room around it.
    # The gradient runs from the accent pushed far into black to the theme's
    # deep purple, so the window -- not the background -- is what you see.
    local R=14 PAD=72 out acc dark w h
    out="$SCR_DIR/$(date +%Y-%m-%d-%H%M%S)_pretty"   # the extension comes from save_as
    acc=$(accent)
    # 28% of the accent: plain integer maths, no colour-space surprises.
    dark=$(printf '#%02x%02x%02x' $((16#${acc:1:2} * 28 / 100)) \
           $((16#${acc:3:2} * 28 / 100)) $((16#${acc:5:2} * 28 / 100)))
    magick "$tmp/shot.png" \
        \( +clone -alpha extract \
           -draw "fill black polygon 0,0 0,$R $R,0 fill white circle $R,$R $R,0" \
           \( +clone -flip \) -compose Multiply -composite \
           \( +clone -flop \) -compose Multiply -composite \) \
        -alpha off -compose CopyOpacity -composite "$tmp/round.png" &&
    magick "$tmp/round.png" \( +clone -background black -shadow 55x22+0+14 \) \
        +swap -background none -layers merge +repage "$tmp/shadow.png" || {
        notify critical "Pretty screenshot failed" "ImageMagick could not process the capture"
        exit 1
    }
    read -r w h < <(magick identify -format '%w %h' "$tmp/shadow.png")
    magick -size "$((w + 2 * PAD))x$((h + 2 * PAD))" \
        -define gradient:angle=135 gradient:"$dark-#1a0b2e" \
        "$tmp/shadow.png" -gravity center -compose over -composite -depth 8 "$tmp/pretty.png" || {
        notify critical "Pretty screenshot failed" "ImageMagick could not compose the background"
        exit 1
    }
    out="$(save_as "$tmp/pretty.png" "$out")" || {
        notify critical "Pretty screenshot not saved" "Could not write into $SCR_DIR"
        exit 1
    }
    if [[ $COPY == on ]]; then
        wl-copy --type image/png < "$tmp/pretty.png"
        notify low "Pretty screenshot saved and copied" "$out"
    else
        notify low "Pretty screenshot saved" "$out"
    fi
}

case "${1:-}" in
    output|region|window) shot "$1" ;;
    region-copy) region_copy ;;
    annotate)    annotate ;;
    ocr)         ocr ;;
    pretty)      pretty "${2:-}" ;;
    *)
        echo "usage: ${0##*/} output|region|window|region-copy|annotate|ocr|pretty [region]" >&2
        exit 2 ;;
esac
