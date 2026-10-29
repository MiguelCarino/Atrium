#!/usr/bin/env bash
# Run once per login (lua/autostart.lua). Rebuilds any plugin that Hyprland
# refused to load -- which after a Hyprland update is all of them, since a
# plugin only loads into the exact version it was built against -- then
# reloads the config so lua/cube.lua and lua/overview.lua load the new .so.
#
# The signal is the real one: the .so is missing, or it exists but is not in
# `hyprctl plugin list`. No version stamp to drift out of sync with manual
# builds.
#
# Builds use --keep: the checkout already carries the local patch, and a
# rebuild against the new headers is what an update needs. Pulling upstream
# at login could leave the patch not applying and nothing built; do that by
# hand (hypr-cube-build.sh / hyprview-build.sh with no argument).
#
# A failed build notifies once per Hyprland version: it leaves
# <name>.so.failed holding that version, and later logins on the same
# Hyprland skip the plugin quietly (plain upstream hypr-cube has no build for
# a new Hyprland until upstream ports it -- one notification, not one per
# login). A Hyprland update tries again; so does running the build script by
# hand, which a success clears.
#   journalctl --user -t hypr-plugins     the build output
set -uo pipefail

dir=$HOME/.config/hypr/scripts
notify=$dir/notify  # notify-send with the theme's mascot (mascot_notify.py)
lib=$HOME/.local/lib/hyprland

# name in `hyprctl plugin list`  .so file      build script
plugins=(
    "hypr-cube                    hypr-cube.so  hypr-cube-build.sh"
    "hyprview                     hyprview.so   hyprview-build.sh"
)

loaded=$(hyprctl plugin list 2>/dev/null)
hlver=$(rpm -q --qf '%{version}-%{release}' hyprland 2>/dev/null)
rebuilt=()
failed=()
for p in "${plugins[@]}"; do
    read -r name so script <<<"$p"
    if [[ -f $lib/$so ]] && grep -q "^Plugin $name by" <<<"$loaded"; then
        continue
    fi
    if [[ -n $hlver && $(cat "$lib/$so.failed" 2>/dev/null) == "$hlver" ]]; then
        continue    # failed on this very Hyprland already; notified then
    fi
    "$notify" -a Hyprland "Rebuilding $name" "It did not load into Hyprland $(rpm -q --qf '%{version}' hyprland); about a minute."
    if "$dir/$script" --keep 2>&1 | systemd-cat -t hypr-plugins; [[ ${PIPESTATUS[0]} -eq 0 ]]; then
        rebuilt+=("$name")
        rm -f "$lib/$so.failed"
    else
        failed+=("$name")
        [[ -n $hlver ]] && mkdir -p "$lib" && printf '%s\n' "$hlver" > "$lib/$so.failed"
    fi
done

if ((${#rebuilt[@]})); then
    hyprctl reload >/dev/null
    "$notify" -a Hyprland "Plugins rebuilt" "${rebuilt[*]}"
fi
if ((${#failed[@]})); then
    "$notify" -a Hyprland -u critical "Plugin rebuild failed" \
        "${failed[*]} -- journalctl --user -t hypr-plugins (tried again after a Hyprland update)"
fi
