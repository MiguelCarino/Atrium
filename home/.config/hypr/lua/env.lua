-- ~/.config/hypr/lua/env.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index). hl.env only; the one
-- module it needs is lua/shared.lua (display.conf, for the pointer).
--
-- These five are ALSO set in ~/.config/uwsm/env. In the uwsm-managed session
-- that file is what systemd services (portal, polkit agent) see, because they
-- are not started by Hyprland and never see hl.env. Change one, change both.

---@module 'hl'

-- ========================= Env =========================
-- XDG_CURRENT_DESKTOP / XDG_SESSION_TYPE / XDG_SESSION_DESKTOP are set by
-- Hyprland itself, so they are not repeated here.
-- The pointer's size and theme: the Settings window's "Fonts & text" page
-- (scripts/font-settings.py) keeps them in display.conf -- cursor_size, and
-- cursor_theme_user over the desktop theme's cursor_theme= (scripts/theme.py,
-- "Your own fonts and cursor") -- and sets them live with hyprctl setcursor.
-- Read here too so a reload, and the next login, start with the same pointer:
-- Hyprland takes its first cursor from XCURSOR_THEME / XCURSOR_SIZE (and
-- HYPRCURSOR_SIZE for hyprcursor themes), and every app it starts inherits
-- them (XWayland apps draw their own pointer from these two). 24 and
-- Adwaita when nothing is set, as before. ~/.config/uwsm/env
-- reads the same keys for the services uwsm starts.
do
    local S = require("lua.shared")
    local st = S.state()
    local size = tonumber(st.cursor_size or "")
    size = (size and size >= 8 and size <= 256) and tostring(math.floor(size)) or "24"
    hl.env("XCURSOR_SIZE", size)
    hl.env("HYPRCURSOR_SIZE", size)
    local home = os.getenv("HOME") or ""
    local function installed(name)
        if not name or name == "" or name:find("/") then return false end
        for _, root in ipairs({ home .. "/.icons", home .. "/.local/share/icons", "/usr/share/icons" }) do
            for _, shape in ipairs({ "default", "left_ptr" }) do
                local f = io.open(root .. "/" .. name .. "/cursors/" .. shape, "r")
                if f then f:close() return true end
            end
        end
        return false
    end
    -- The theme's cursor_theme=, following inherit= like theme.py's chain()
    -- (cyberpunk is the base and says Adwaita).
    local want = st.cursor_theme_user
    if not installed(want) then
        want = nil
        local themes = home .. "/.config/themes/"
        local name, seen = (st.theme and st.theme ~= "") and st.theme or "cyberpunk", {}
        while name and not seen[name] and not want do
            seen[name] = true
            local conf = S.read_kv(themes .. name .. "/theme.conf")
            if not conf then break end
            if conf.cursor_theme and conf.cursor_theme ~= "" then want = conf.cursor_theme end
            name = (conf.inherit and conf.inherit ~= "") and conf.inherit or (name ~= "cyberpunk" and "cyberpunk" or nil)
        end
        -- No theme names one: Adwaita, theme.py's default (DEFAULTS).
        if not installed(want) then want = installed("Adwaita") and "Adwaita" or nil end
    end
    if want then hl.env("XCURSOR_THEME", want) end
end
hl.env("QT_QPA_PLATFORM", "wayland")
-- Qt6 apps (qBittorrent, Okular, Ark...) take style and palette from
-- ~/.config/qt6ct, set to the dark COSMIC palette. The qt5ct/qt6ct configs
-- were there before this line, but nothing loaded them. Qt5 apps look for a
-- plugin named after this value and, finding no "qt6ct" for Qt5, keep their
-- defaults. Also in ~/.config/uwsm/env; keep the two in step.
hl.env("QT_QPA_PLATFORMTHEME", "qt6ct")
-- Absolute on purpose: env values are not shell-expanded, so a leading ~ would
-- reach apps as a literal character -- hence $HOME read here. Same directory
-- hyprshot writes to (scrDir in lua/shared.lua).
hl.env("XDG_SCREENSHOTS_DIR", (os.getenv("HOME") or "") .. "/Pictures/Screenshots")

-- Japanese input (fcitx5 + mozc). The daemon itself starts in the autostart
-- block (lua/autostart.lua).
--
-- This is the ONLY env var set for the IME, and the omissions are deliberate.
--
-- Hyprland implements text-input-v3, so every Wayland-native app here --
-- cosmic-term, cosmic-files, alacritty, Firefox -- talks to fcitx5 over the
-- Wayland protocol directly and needs no env var at all. XMODIFIERS is purely
-- for XWayland clients, which have no such protocol and fall back to XIM.
--
-- GTK_IM_MODULE and QT_IM_MODULE are the two you will find in every forum post
-- on this, and setting them here is a downgrade, not insurance: they force
-- toolkit apps off text-input-v3 and onto the older module path, which on GTK4
-- ranges from worse (preedit in a detached popup instead of inline) to broken.
-- Leave them unset unless one specific app misbehaves, and then set it for that
-- app only rather than session-wide. Electron/Chromium is the usual offender
-- and its real fix is the --enable-wayland-ime flag, not these.
hl.env("XMODIFIERS", "@im=fcitx")
-- NVIDIA (tested on an RTX 40-series, driver 615, open kernel module): deliberately NO env vars.
--
-- Every Hyprland-on-NVIDIA guide lists LIBVA_DRIVER_NAME=nvidia,
-- NVD_BACKEND=direct, __GLX_VENDOR_LIBRARY_NAME=nvidia and
-- ELECTRON_OZONE_PLATFORM_HINT=auto. Each was checked on this machine (Oct 2026)
-- and each is already the default behaviour:
--
--   LIBVA_DRIVER_NAME / NVD_BACKEND   vainfo with no env picks "VA-API NVDEC
--       driver [direct backend]" and lists H.264, HEVC Main10, VP9 and AV1.
--       Needs libva-nvidia-driver (installed); nvidia_drm modeset=Y.
--   __GLX_VENDOR_LIBRARY_NAME         glxinfo under XWayland already reports
--       "NVIDIA Corporation". Forcing it is known to break some XWayland apps.
--   ELECTRON_OZONE_PLATFORM_HINT      VSCodium and Heroic (both Flatpak) start
--       as native Wayland clients without it; VSCodium passes
--       --ozone-platform=wayland --enable-wayland-ime itself.
--
-- Revisit if a driver or Electron update changes that: vainfo, glxinfo -B,
-- and the xwayland field in `hyprctl clients` are the three checks.
--
-- WLR_NO_HARDWARE_CURSORS removed (dead since the aquamarine switch).
-- If the cursor glitches, use: hl.config({ cursor = { no_hardware_cursors = true } })
