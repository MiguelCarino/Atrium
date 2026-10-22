#!/usr/bin/env python3
"""Write this machine's screen layout -- as it is right now -- to
~/.config/hypr/lua/hosts/<hostname>.lua, which lua/monitors.lua loads from
then on (and the dotfiles carry to a reinstall of the same machine).

    monitors-capture.py            write it (an existing file is kept as .bak)
    monitors-capture.py --print    only show it

Arrange the screens first (any way Hyprland lets you: hyprctl keyword
monitor, nwg-displays...), then run this once. Each screen keeps its mode,
position, scale and rotation as its default; a screen in HDR gets cm =
"hdredid" plus the SDR settings the HDR switch needs. The blocks go through
the screen() that lua/monitors.lua hands to apply(), so Settings > Screens'
choices (display.py rate / resolution / scale / rotate / position / mirror /
vrr / bitdepth / screen, kept in display.conf) still lay over them.
"""
import json
import os
import re
import socket
import subprocess
import sys

HOSTS = os.path.expanduser("~/.config/hypr/lua/hosts")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screens  # noqa: E402  (live_order(): the order the screens are written in)


def host():
    return re.sub(r"[^\w]", "_", socket.gethostname().split(".")[0])


def block(m):
    hdr = m.get("colorManagementPreset", "").startswith("hdr")
    rate = f"{m['refreshRate']:.2f}".rstrip("0").rstrip(".")
    lines = [f'        output   = "{m["name"]}",',
             f'        mode     = "{m["width"]}x{m["height"]}@{rate}",',
             f'        position = "{m["x"]}x{m["y"]}",',
             f'        scale    = {m["scale"]:g},',
             f'        transform = {m["transform"]},',
             '        vrr      = 0,']
    if hdr:
        lines += ['        bitdepth = 10,',
                  '        supports_hdr = 1,',
                  f'        cm = (st["hdr.{m["name"]}"] ~= "off") and "hdredid" or "srgb",',
                  f'        sdr_max_luminance = tonumber(st["sdr_white.{m["name"]}"]) or 220,']
    return f'    -- {m.get("description", "")}\n    screen({{\n' + "\n".join(lines) + "\n    })"


def text(mons):
    hdr = ", ".join(f'["{m["name"]}"] = true' for m in mons
                    if m.get("colorManagementPreset", "").startswith("hdr"))
    blocks = "\n\n".join(block(m) for m in mons)
    order = ", ".join(f'"{n}"' for n in screens.live_order(mons))
    return f"""-- ~/.config/hypr/lua/hosts/{host()}.lua -- this machine's screens, written by
-- scripts/monitors-capture.py from the live layout. Edit freely; loaded by
-- lua/monitors.lua when the hostname is "{host()}".

---@module 'hl'

local S = require("lua.shared")

local M = {{}}
M.hdr_capable = {{ {hdr} }}
-- The screens in order: the first is the primary (workspaces 1, 2, 3, 5, the
-- bar), the second gets workspace 4, the third 6 (lua/rules.lua). Written as
-- the screen at 0x0 first, then Hyprland's order; reorder freely, but keep
-- this and the line above on one line each (scripts/screens.py reads them).
M.screens = {{ {order} }}

-- screen: lua/monitors.lua's, which lays the display.conf choices over each
-- block (rate.<output>, mode.<output>, scale.<output> ...). Called with none
-- (by hand, say) it is plain hl.monitor and the blocks below as written.
function M.apply(screen)
    screen = screen or hl.monitor
    local st = S.state()

{blocks}
end

return M
"""


def main(argv):
    mons = json.loads(subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True).stdout or "[]")
    if not mons:
        sys.exit("monitors-capture: hyprctl gave no screens (is Hyprland running?)")
    out = text(mons)
    if "--print" in argv:
        print(out)
        return
    os.makedirs(HOSTS, exist_ok=True)
    path = os.path.join(HOSTS, f"{host()}.lua")
    if os.path.exists(path):
        os.replace(path, path + ".bak")
    with open(path, "w") as handle:
        handle.write(out)
    print(f"wrote {path}" + (" (the old one is .bak)" if os.path.exists(path + ".bak") else ""))
    print("hyprctl reload  -- to load it now")


if __name__ == "__main__":
    main(sys.argv[1:])
