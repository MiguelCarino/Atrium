-- ~/.config/hypr/lua/autostart.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index), last. The
-- hyprland.start event fires once per login, NOT on `hyprctl reload`, so
-- nothing in here re-runs when the config is reloaded.

---@module 'hl'

-- ========================= Autostart =========================
-- The long-running daemons are systemd user services, not exec lines:
--
--   waybar  hyprpaper  hypridle  mako      Fedora's own units, enabled
--   wallpaper-slideshow  workspace-tint    ~/.config/systemd/user/*.service
--   cliphist@text  cliphist@image          (cliphist@.service, one per type)
--   hyprpolkitagent                        Fedora's unit, enabled
--
-- uwsm starts them through graphical-session.target, so each one is restarted
-- if it crashes, logs to the journal (`journalctl --user -u waybar`) and is
-- stopped cleanly at logout. Everything in ~/.config/systemd/user/ is in the
-- dotfiles repo; the local tweaks to the Fedora units are the
-- <unit>.service.d/hyprland.conf drop-ins next to them. Each unit only runs
-- when XDG_CURRENT_DESKTOP is Hyprland, so a COSMIC login does not get them.
--
--   systemctl --user status waybar          is it running, last log lines
--   systemctl --user restart waybar         what ALT+G does
--
-- What each one is for:
--   hyprpaper            wallpapers; images in hyprpaper.conf
--   wallpaper-slideshow  rotates ~/Pictures/Wallpapers/<OUTPUT>/ through
--                        hyprpaper (10 min of the wallpaper being visible per
--                        change; paused while windows cover it). Bound to
--                        hyprpaper.service: it restarts with it and puts back
--                        each monitor's remembered image.
--   workspace-tint       rewrites waybar/generated/*.css so a workspace pill
--                        wears the colour of the monitor it is on NOW
--                        (summon() in lua/binds.lua re-homes workspaces);
--                        waybar picks the change up via reload_style_on_change.
--   hypridle             reads hypridle.conf
--   mako                 owns org.freedesktop.Notifications; without it
--                        Firefox/Thunderbird draw notifications as tiled windows
--   cliphist@*           records the clipboard for SUPER+V
--   hyprpolkitagent      password prompts for GUI apps needing admin rights
--
-- The plain "Hyprland" session (not uwsm-managed) never reaches
-- graphical-session.target, so there the same programs are started from here
-- instead. uwsm puts UWSM_* variables into Hyprland's environment, which is how
-- the two sessions are told apart.
local under_uwsm = os.getenv("UWSM_FINALIZE_VARNAMES") ~= nil

local fallback_daemons = {
    "hyprpaper",
    "python3 ~/.config/hypr/scripts/wallpaper-slideshow.py",
    "waybar",
    "python3 ~/.config/waybar/scripts/workspace-tint.py watch",
    "hypridle",
    "wl-paste --type text --watch cliphist store",
    "wl-paste --type image --watch cliphist store",
    "mako",
    "systemctl --user start hyprpolkitagent",
}

hl.on("hyprland.start", function()
    if not under_uwsm then
        for _, cmd in ipairs(fallback_daemons) do hl.exec_cmd(cmd) end
    end
    -- Japanese input. Input methods list lives in ~/.config/fcitx5/profile;
    -- XMODIFIERS is set in the env block (lua/env.lua).
    --
    -- Still an exec line: fcitx5 has no user unit on Fedora, and it is not a
    -- crash risk worth one. -d daemonizes. --replace matters when it is
    -- started by hand next to a running one: without it the second finds the
    -- D-Bus name taken and exits, leaving the stale instance with the old
    -- config.
    --
    -- SUPER+Space walks both switchers as one list: us -> latam -> Japanese
    -- (mozc) -> us (lua/binds.lua, scripts/input-settings.py cycle). fcitx5's
    -- own Ctrl+Space trigger is off (~/.config/fcitx5/config). Underneath the
    -- two still stack: the xkb group decides which letters the physical keys
    -- produce, mozc then reads those letters as romaji.
    --
    -- --disable=notificationitem: no fcitx5 icon in the tray. The bar's
    -- keyboard-layout pill (hyprland/language, scripts/language_panel.py)
    -- already shows and picks the layout and the input method, and the icon
    -- sat next to it in the toolbox card as a second keyboard.
    hl.exec_cmd("fcitx5 -d --replace --disable=notificationitem")

    -- After a Hyprland update the cube and overview plugins no longer load;
    -- this rebuilds whichever did not and reloads (see the script's header).
    hl.exec_cmd("~/.config/hypr/scripts/plugins-check.sh")
end)
