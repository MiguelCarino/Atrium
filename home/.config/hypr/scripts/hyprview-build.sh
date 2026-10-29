#!/usr/bin/env bash
# Build the hyprview overview plugin (github.com/yz778/hyprview) against the
# Hyprland that is installed right now, without root and without hyprpm.
#
#   hyprview-build.sh          pull the latest hyprview, build, install
#   hyprview-build.sh --keep   rebuild the checkout as it is (no git pull)
#
# Run it after every Hyprland update. A plugin is compiled against one exact
# Hyprland version; Hyprland refuses to load a mismatched one (you get an error
# notification at login and no overview, nothing worse), so the overview stays
# broken until this has been run.
#
# Why not hyprpm: it needs sudo for its state store and builds headers from a
# Hyprland git checkout. The headers this machine's Hyprland was actually built
# with are in the COPR's hyprland-devel package, so this script `dnf download`s
# that (plus the -devel packages its headers include) for the installed
# versions and unpacks them into a throwaway directory. Nothing is installed
# system-wide.
#
# Output: ~/.local/lib/hyprland/hyprview.so, loaded by lua/overview.lua.
set -euo pipefail

SRC=$HOME/.local/src/hyprview
OUT=$HOME/.local/lib/hyprland/hyprview.so

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [[ ! -d $SRC/.git ]]; then
    git clone -q https://github.com/yz778/hyprview "$SRC"
elif [[ ${1:-} != --keep ]]; then
    # Drop the previous run's patch so the pull is a clean fast-forward.
    git -C "$SRC" checkout -q -- .
    git -C "$SRC" pull -q --ff-only
fi

# Local changes on top of upstream, kept in scripts/hyprview.patch:
#   - rotated monitors: layout uses the rotated (logical) size, and window /
#     background captures are taken unrotated, so a portrait screen gets a
#     portrait overview with upright tiles
#   - the mouse wheel over an overview steps that monitor through its
#     workspaces (down = next, up = previous) and the tiles slide in; the
#     "next" / "prev" dispatcher args do the same from a key
# If upstream changes the same lines the patch stops applying; the build then
# stops here rather than shipping a plugin without them.
#
# Hyprland 0.57 reworked the plugin API (every draw takes a render context,
# workspace ids became a variant, window title/class moved into metadata(),
# the keybind manager and a few headers moved). Upstream has no 0.57 port yet,
# so scripts/hyprview-hl057.patch ports upstream + hyprview.patch; it goes on
# top only when the installed Hyprland is 0.57 or newer, and a 0.56 build is
# still exactly upstream + hyprview.patch. A checkout that carries the port
# when building for 0.56 gets it taken back out.
PATCH=$HOME/.config/hypr/scripts/hyprview.patch
PORT=$HOME/.config/hypr/scripts/hyprview-hl057.patch
hlver=$(rpm -q --qf '%{version}' hyprland 2>/dev/null) || hlver=999  # not an rpm: the newest headers get fetched
hl057=0
[[ $(printf '%s\n' 0.57.0 "$hlver" | sort -V | head -1) == 0.57.0 ]] && hl057=1

applied() { git -C "$SRC" apply --check -R "$1" 2>/dev/null; }
patchfail() {
    echo "hyprview: scripts/${1##*/} no longer applies to upstream $(git -C "$SRC" log -1 --format=%h); fix it or build with --keep" >&2
    exit 1
}
if applied "$PORT"; then
    ((hl057)) || git -C "$SRC" apply -R "$PORT"
else
    applied "$PATCH" || git -C "$SRC" apply "$PATCH" || patchfail "$PATCH"
    if ((hl057)); then
        # Files the port adds are untracked, so the "checkout -- ." above
        # leaves them behind and they would block a fresh apply.
        git -C "$SRC" apply --summary "$PORT" | awk '$1 == "create" {print $4}' |
            while read -r f; do rm -f "${SRC:?}/$f"; done
        git -C "$SRC" apply "$PORT" || patchfail "$PORT"
    fi
fi

# "-devel package to fetch" -> "installed runtime package whose version it must match".
# lua/glslang only contribute headers Hyprland's own headers include.
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

# The .pc files say prefix=/usr; point them at the unpacked tree. hyprland.pc
# is the odd one out with prefix=/usr/include.
sed -i "s|^prefix=/usr/include$|prefix=$work/usr/include|; s|^prefix=/usr$|prefix=$work/usr|" \
    "$work"/usr/share/pkgconfig/*.pc "$work"/usr/lib64/pkgconfig/*.pc
export PKG_CONFIG_PATH=$work/usr/share/pkgconfig:$work/usr/lib64/pkgconfig

make -C "$SRC/src" clean >/dev/null
make -C "$SRC/src" all -j"$(nproc)" 2>&1 | grep -E 'error' || true
[[ -f $SRC/build/hyprview.so ]] || { echo "hyprview: build failed" >&2; exit 1; }

# Copy then rename: the running Hyprland has the old .so mapped, and writing
# over it in place would change code under its feet.
mkdir -p "${OUT%/*}"
cp "$SRC/build/hyprview.so" "$OUT.new"
mv -f "$OUT.new" "$OUT"
rm -f "$OUT.failed"   # plugins-check.sh: built, so try it again at login
echo "hyprview: built $(git -C "$SRC" log -1 --format=%h) against Hyprland $(rpm -q --qf '%{version}' hyprland) -> $OUT"
echo "Log out and back in (or reload Hyprland) to load it."
