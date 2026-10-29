#!/usr/bin/env bash
# Build the hypr-cube plugin (github.com/dmty/hypr-cube) -- Compiz-style cube
# workspace switching -- against the Hyprland that is installed right now,
# without root and without hyprpm. Same recipe as hyprview-build.sh; see that
# script for why hyprpm is not used.
#
#   hypr-cube-build.sh          pull the latest hypr-cube, build, install
#   hypr-cube-build.sh --keep   rebuild the checkout as it is (no git pull)
#
# Run it after every Hyprland update: a plugin is compiled against one exact
# Hyprland commit and refuses to load into any other (an error notification at
# login and plain workspace switching, nothing worse).
#
# Output: ~/.local/lib/hyprland/hypr-cube.so, loaded by lua/cube.lua.
set -euo pipefail

SRC=$HOME/.local/src/hypr-cube
OUT=$HOME/.local/lib/hyprland/hypr-cube.so

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [[ ! -d $SRC/.git ]]; then
    git clone -q https://github.com/dmty/hypr-cube "$SRC"
elif [[ ${1:-} != --keep ]]; then
    git -C "$SRC" checkout -q -- .
    git -C "$SRC" pull -q --ff-only
fi

# Local changes on top of upstream, kept in scripts/hypr-cube.patch:
#   - faces are the workspaces that live on the focused monitor (sorted by id),
#     not workspaces 1..faces -- workspaces here are spread over three screens,
#     and spinning DP-1 onto workspace 4 (DP-2's) would yank focus across
#   - float_depth: floating windows get their own layer per face that hovers
#     in front of the cube while it turns
#   - live: visible faces re-rendered every frame, so video keeps playing
#   - cube.go1..go9: spin straight to a workspace (SUPER+CTRL+n)
#   - a landing commits even if focus wandered to another monitor mid-spin
#     (upstream skipped the switch, showing one face then the old workspace)
#   - fling: a released drag keeps its momentum
#   - queued spins: input mid-spin extends or re-aims the rotation
#
# scripts/plugins-check.sh runs this with --keep at login whenever the plugin
# failed to load (i.e. after a Hyprland update).
#
# The patch is optional: without it (Atrium ships without it until upstream
# has a licence) this builds plain upstream. lua/cube.lua only asks for the
# patch's settings and keys when $OUT.patched says the build has them.
#
# Hyprland 0.57 reworked the plugin API (every draw takes a render context, the
# render pass and render data moved into it, workspace ids became a variant,
# CMonitor::activeWorkspaceID() is gone). Upstream has no 0.57 port yet, so
# scripts/hypr-cube-hl057.patch ports upstream + hypr-cube.patch; it goes on
# top only when the installed Hyprland is 0.57 or newer, and a 0.56 build is
# still exactly upstream + hypr-cube.patch. It needs hypr-cube.patch under it:
# plain upstream has no 0.57 build here.
PATCH=$HOME/.config/hypr/scripts/hypr-cube.patch
PORT=$HOME/.config/hypr/scripts/hypr-cube-hl057.patch
hlver=$(rpm -q --qf '%{version}' hyprland 2>/dev/null) || hlver=999  # not an rpm: the newest headers get fetched
hl057=0
[[ $(printf '%s\n' 0.57.0 "$hlver" | sort -V | head -1) == 0.57.0 ]] && hl057=1

applied() { git -C "$SRC" apply --check -R "$1" 2>/dev/null; }
patchfail() {
    echo "hypr-cube: scripts/${1##*/} no longer applies to upstream $(git -C "$SRC" log -1 --format=%h); fix it or build with --keep" >&2
    exit 1
}
patched=0
if [[ -f $PATCH ]]; then
    if [[ -f $PORT ]] && applied "$PORT"; then
        ((hl057)) || git -C "$SRC" apply -R "$PORT"
    else
        applied "$PATCH" || git -C "$SRC" apply "$PATCH" || patchfail "$PATCH"
        if ((hl057)) && [[ -f $PORT ]]; then
            # Files the port adds are untracked, so the "checkout -- ." above
            # leaves them behind and they would block a fresh apply.
            git -C "$SRC" apply --summary "$PORT" | awk '$1 == "create" {print $4}' |
                while read -r f; do rm -f "${SRC:?}/$f"; done
            git -C "$SRC" apply "$PORT" || patchfail "$PORT"
        fi
    fi
    patched=1
fi
if ((hl057)) && ! { [[ -f $PATCH && -f $PORT ]] && applied "$PORT"; }; then
    # Not fatal: a later upstream may have its own port.
    echo "hypr-cube: building plain upstream against Hyprland $hlver; as of upstream 0f33587 that needs scripts/hypr-cube-hl057.patch (on top of scripts/hypr-cube.patch)" >&2
fi

# Headers: the -devel packages matching the installed runtime versions,
# unpacked into $work (nothing installed system-wide). As in hyprview-build.sh.
declare -A pkgs=(
    [hyprland-devel]=hyprland   [aquamarine-devel]=aquamarine
    [hyprutils-devel]=hyprutils [hyprlang-devel]=hyprlang
    [hyprcursor-devel]=hyprcursor [hyprgraphics-devel]=hyprgraphics
    [libinput-devel]=libinput   [xcb-util-wm-devel]=xcb-util-wm
    [xcb-util-errors-devel]=xcb-util-errors
    [lua-devel]=lua-libs        [glslang-devel]=glslang
)
specs=()
for dev in "${!pkgs[@]}"; do
    if v=$(rpm -q --qf '%{version}-%{release}' "${pkgs[$dev]}" 2>/dev/null); then
        specs+=("$dev-$v.x86_64")
    else
        specs+=("$dev.x86_64")
    fi
done
( cd "$work" && dnf download -q "${specs[@]}" )
for r in "$work"/*.rpm; do
    ( cd "$work" && rpm2cpio "$r" | cpio -idm --quiet )
done
sed -i "s|^prefix=/usr/include$|prefix=$work/usr/include|; s|^prefix=/usr$|prefix=$work/usr|" \
    "$work"/usr/share/pkgconfig/*.pc "$work"/usr/lib64/pkgconfig/*.pc
export PKG_CONFIG_PATH=$work/usr/share/pkgconfig:$work/usr/lib64/pkgconfig

rm -f "$SRC/hypr-cube.so"
make -C "$SRC" all 2>&1 | grep -E 'error' || true
[[ -f $SRC/hypr-cube.so ]] || { echo "hypr-cube: build failed" >&2; exit 1; }

# Copy then rename: the running Hyprland has the old .so mapped.
mkdir -p "${OUT%/*}"
cp "$SRC/hypr-cube.so" "$OUT.new"
mv -f "$OUT.new" "$OUT"
rm -f "$OUT.failed"   # plugins-check.sh: built, so try it again at login
if (( patched )); then touch "$OUT.patched"; else rm -f "$OUT.patched"; fi
echo "hypr-cube: built $(git -C "$SRC" log -1 --format=%h) against Hyprland $(rpm -q --qf '%{version}' hyprland) -> $OUT"
