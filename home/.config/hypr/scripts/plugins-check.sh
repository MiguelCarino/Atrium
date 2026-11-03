#!/usr/bin/env bash
# Run once per login (lua/autostart.lua). Rebuilds any plugin that Hyprland
# refused to load, or that was built against a different Hyprland package or
# library than the ones installed now, then reloads the config so lua/cube.lua
# and lua/overview.lua load the new .so.
#
# Two signals. The .so is missing or not in `hyprctl plugin list` (a new
# Hyprland version refuses it). Or its <name>.so.built stamp, written by the
# build script (so manual builds keep it in sync too), differs from
# scripts/plugin-stamp: Hyprland rebuilt at the same version against new
# aquamarine / hyprgraphics / hyprutils still loads the old .so, which then
# crashes or freezes the compositor (2026-11-02: the overview on an empty
# workspace froze the session after 0.57.0-1 -> 0.57.0-2). A .so with no
# stamp counts as stale.
#
# Builds use --keep: the checkout already carries the local patch, and a
# rebuild against the new headers is what an update needs. Pulling upstream
# at login could leave the patch not applying and nothing built; do that by
# hand (hypr-cube-build.sh / hyprview-build.sh with no argument).
#
# A failed build notifies once per Hyprland build: it leaves <name>.so.failed
# holding the stamp it failed against, and later logins on the same packages
# skip the plugin quietly (plain upstream hypr-cube has no build for
# a new Hyprland until upstream ports it -- one notification, not one per
# login). A Hyprland or library update tries again; so does running the build script by
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
stamp=$("$dir/plugin-stamp")
rebuilt=()
failed=()
for p in "${plugins[@]}"; do
    read -r name so script <<<"$p"
    if [[ -f $lib/$so ]] && grep -q "^Plugin $name by" <<<"$loaded"; then
        # Loaded; current only if built against these very packages.
        [[ -n $stamp && $(cat "$lib/$so.built" 2>/dev/null) == "$stamp" ]] && continue
        why="It was built against an older Hyprland or its libraries"
    else
        why="It did not load into Hyprland $(rpm -q --qf '%{version}' hyprland)"
    fi
    if [[ -n $stamp && $(cat "$lib/$so.failed" 2>/dev/null) == "$stamp" ]]; then
        continue    # failed on these very packages already; notified then
    fi
    "$notify" -a Hyprland "Rebuilding $name" "$why; about a minute."
    if "$dir/$script" --keep 2>&1 | systemd-cat -t hypr-plugins; [[ ${PIPESTATUS[0]} -eq 0 ]]; then
        rebuilt+=("$name")
        rm -f "$lib/$so.failed"
    else
        failed+=("$name")
        [[ -n $stamp ]] && mkdir -p "$lib" && printf '%s\n' "$stamp" > "$lib/$so.failed"
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
