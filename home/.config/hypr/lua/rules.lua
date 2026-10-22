-- ~/.config/hypr/lua/rules.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index). Window rules, layer
-- rules and workspace rules, in that order.
--
-- ORDER MATTERS within this file: window rules are evaluated in the order
-- they are declared, so moving a block around can change which value wins
-- when two rules set the same property on one window. The two Steam-game
-- rules sat in the Monitors section of the single-file config and still run
-- first, exactly as they did there.

---@module 'hl'

-- The screens, by role rather than by connector name, so the rules below fit
-- any machine. lua/monitors.lua answers from this machine's host file
-- (lua/hosts/<hostname>.lua: M.screens, in order) or, with none, from the
-- live screens:
--   P       the primary -- display.conf's primary=<o> (Settings > Screens,
--           scripts/display.py primary), else the host file's first screen
--   SCREENS the screens in order; the second gets workspace 4, the third 6
-- Read at every load, so a choice survives a reload and a re-login. pcall:
-- if lua/monitors.lua ever fails to load, nothing is pinned (P nil) rather
-- than the whole file failing with it.
local mon_ok, MON = pcall(require, "lua.monitors")
local P = mon_ok and type(MON) == "table" and MON.primary and MON.primary() or nil
local SCREENS = mon_ok and type(MON) == "table" and MON.order and MON.order() or {}

-- ========================= Window rules: Steam games =========================
-- Games open on the primary screen (the one in front of you, and the HDR one
-- on a machine whose host file makes it primary).
if P then
    hl.window_rule({
        name  = "steam-games-to-primary",
        match = { class = "^(steam_app_.*)$" },
        monitor = P,
    })
end

-- Steam games open truly fullscreen: (2,2), Hyprland fills the monitor AND
-- the game is told it is fullscreen, so it takes its fullscreen render path.
-- A fullscreen window draws above waybar, so the bar is out of the way on
-- the primary only; the other screens keep theirs, notifications still show.
--
-- This used to be mode A, (0,2) -- an ordinary tiled window that the game
-- believed was fullscreen (see ~/.config/waybar/scripts/fsstate.py). Dropped
-- Oct 2026: a game that only offers the monitor's own resolutions (Resident
-- Evil Requiem: the panel's native mode or nothing) rendered past the bottom of its
-- shorter tile, and when it slipped out floating at 0,0 instead, the bar covered its
-- top 36px -- FPS counter included.
--
-- The state has to be set at map time, by a rule rather than a keypress: a
-- game decides which render path to use when it first sees the state, and
-- several of them never re-check.
--
-- The value is a string, "internal client", in that order -- NOT a table.
-- Passing { internal = 0, client = 2 } is rejected with "string type requires
-- a string", which is easy to misread as the rule not existing.
--
-- float = false: a Steam game arrives floating; tiled, ALT+F (or the reset
-- key below) leaves an ordinary tiled window under the bar, not a
-- screen-sized float covering it.
--
-- Every Steam game, not a list of appids. steam_app_<appid> is assigned by
-- Steam itself, so the pattern is exactly as reliable as naming them one by
-- one -- it is the same selector the primary-screen rule above already trusts.
--
-- Per-game escape hatches are runtime keys, not config edits -- you find out a
-- game is unhappy while you are looking at it: ALT+SHIFT+F mode A (the old
-- behaviour), ALT+CTRL+F mode B (borderless: fills the screen, game told
-- windowed), ALT+CTRL+SHIFT+F plain window.
--
-- If some game turns out to need a permanent exemption, do NOT reach for a
-- negative: match without testing that it really excludes. It parses happily,
-- which is the dangerous part -- a selector that silently matches nothing (or
-- everything) looks like the rule being broken rather than the pattern being
-- wrong. Same trap as the mako namespace further down.
hl.window_rule({
    name  = "fs-render-windowed-steam",
    match = { class = "^(steam_app_.*)$" },
    float = false,
    fullscreen_state = "2 2",
})

-- Games are always opaque. Some engines hand the compositor a surface with an
-- alpha channel they never meant to be used (the P.T. port in
-- ~/.local/share/pt-pc-port, class "pt", is one: native Wayland, opacity 1.0
-- everywhere, and the desktop still showed through dark scenes). force_rgbx
-- tells Hyprland to ignore the alpha channel, so it is not a decoration
-- opacity setting -- active/inactive_opacity are 1.0 already and were never
-- the cause. no_blur goes with it: there is nothing behind an opaque window
-- worth blurring, and the blur pass is GPU time taken from the game.
--
-- Another game showing the desktop through it: add its class here
-- (`hyprctl clients` prints it).
hl.window_rule({
    name       = "games-opaque",
    match      = { class = "^(steam_app_.*|pt)$" },
    force_rgbx = true,
    no_blur    = true,
})

-- Browsers and mpv are always opaque too: pages and video are content, the
-- wallpaper never belongs behind them. Same pair as the games -- force_rgbx
-- drops whatever alpha the app's surface carries (a translucent GTK theme,
-- a page with a transparent background), no_blur skips the wasted pass.
-- Chrome's Flatpak still calls itself google-chrome.
hl.window_rule({
    name       = "browsers-mpv-opaque",
    match      = { class = "^(org\\.mozilla\\.firefox|firefox|google-chrome|chromium-browser|[Cc]hromium|org\\.gnome\\.Epiphany|mpv)$" },
    force_rgbx = true,
    no_blur    = true,
})

-- ========================= Window rules: behaviour =========================
-- Idle: a fullscreen window keeps hypridle from dimming, locking or switching
-- the screens off. Browsers and mpv inhibit idle on their own while playing,
-- but a controller-driven game sends no keyboard or mouse input at all, so
-- without this the lock lands 10 minutes into a match and DPMS at 15.
--
-- "fullscreen" here means Hyprland-fullscreen (ALT+F or a game that takes the
-- whole screen). Steam games get their own rule just below anyway: a game
-- dropped out of fullscreen (ALT+F, the mode keys) should still keep the
-- screen awake.
hl.window_rule({
    name         = "idle-inhibit-fullscreen",
    match        = { class = ".*" },
    idle_inhibit = "fullscreen",
})
hl.window_rule({
    name         = "idle-inhibit-steam-games",
    match        = { class = "^(steam_app_.*)$" },
    idle_inhibit = "always",
})

-- Apps asking to be maximized fight the tiler: the window flashes to full size
-- and then snaps back into its tile. Ignore the request; ALT+F is the way to
-- make something big. (From Hyprland's own bundled example config.)
hl.window_rule({
    name           = "suppress-maximize-events",
    match          = { class = ".*" },
    suppress_event = "maximize",
})

-- XWayland menus and drag-and-drop helpers are nameless floating surfaces that
-- steal focus and break drags out of Steam and other X11 apps. No focus for
-- them. (Also from the bundled example.)
hl.window_rule({
    name     = "fix-xwayland-drags",
    match    = {
        class      = "^$",
        title      = "^$",
        xwayland   = true,
        float      = true,
        fullscreen = false,
        pin        = false,
    },
    no_focus = true,
})

-- ========================= Window rules: floating =========================
-- File dialogs. Tiled, an "Open File" splits whatever you were working in and
-- shoves it to half width for the few seconds it is up; floating and centred
-- it sits on top and leaves the layout alone. Matched on title because the
-- dialog's class is its parent app's (firefox, chrome, codium...), and on the
-- portal's own class for apps that go through xdg-desktop-portal.
hl.window_rule({
    name   = "float-file-dialogs",
    match  = { title = "^(Open File|Open Files|Open Folder|Save File|Save As|Save Image|File Upload|Choose Files?|Select a File|Enter name of file to save to).*$" },
    float  = true,
    center = true,
    size   = "1100 700",
})
hl.window_rule({
    name   = "float-portal-file-chooser",
    match  = { class = "^(xdg-desktop-portal-gtk)$" },
    float  = true,
    center = true,
    size   = "1100 700",
})

-- Small utility windows that are useless at tile size: the volume mixer, the
-- network editor, and the polkit password prompt (hyprpolkitagent). Centred so
-- they open where you are looking rather than wherever the layout decides.
hl.window_rule({
    name   = "float-utilities",
    match  = { class = "^(org\\.pulseaudio\\.pavucontrol|pavucontrol|nm-connection-editor|hyprpolkitagent)$" },
    float  = true,
    center = true,
    size   = "900 600",
})

-- Steam's side windows (friends list, settings, the "Steam is starting"
-- splash) are separate toplevels with the same class as the main client.
-- Matching them by title, positively, rather than "class steam AND title not
-- Steam" -- see the warning about negative: matches on the game rule above.
hl.window_rule({
    name  = "float-steam-side-windows",
    match = { class = "^(steam)$", title = "^(Friends List|Steam Settings|Sign in to Steam|Steam - News.*|Special Offers)$" },
    float = true,
})

-- Picture-in-picture: float, pinned (stays on screen across workspace
-- switches), fixed 16:9 in the bottom-right corner of whichever monitor it
-- opens on, clear of the bar. Firefox titles it "Picture-in-Picture", Chrome
-- "Picture in picture"; both spellings match. keep_aspect_ratio means
-- ALT+RMB resizing it does not letterbox the video.
--
-- move is the window size plus a 24px margin (640+24, 360+24), spelled out
-- because 0.56's move expressions do not resolve window_w / window_h -- tested,
-- the window landed at the top-left instead. Change size, change move with it.
hl.window_rule({
    name              = "pip",
    match             = { title = "^(Picture-in-Picture|Picture in picture)$" },
    float             = true,
    pin               = true,
    keep_aspect_ratio = true,
    size              = "640 360",
    move              = "monitor_w-664 monitor_h-384",
})

-- ========================= Window rules: placement =========================
-- Apps with a fixed home. "silent" opens them there without dragging focus
-- along, so launching mail does not throw you onto another screen mid-sentence.
--
--   4 (second screen)    mail -- glanceable, rarely the thing you type into
--   5 (primary)          game launchers, so the client is out of the way of
--                        workspaces 1-3 and the game itself (steam_app_*,
--                        pinned to the primary above) lands next to it
--
-- Workspace numbers are the persistent ones from the rules below; if you
-- renumber those, renumber these.
hl.window_rule({
    name      = "mail-to-ws4",
    match     = { class = "^(thunderbird|org\\.mozilla\\.Thunderbird|net\\.thunderbird\\.Thunderbird)$" },
    workspace = "4 silent",
})
hl.window_rule({
    name      = "launchers-to-ws5",
    -- Heroic is a Flatpak, so its class is the app ID, not "heroic" -- tested.
    match     = { class = "^(steam|com\\.heroicgameslauncher\\.hgl)$" },
    workspace = "5 silent",
})

-- The Settings window (scripts/settings.py, app id desktop.settings): a
-- floating card in the middle of the screen it opens on, not a tile.
hl.window_rule({
    name   = "desktop-settings",
    match  = { class = "^(desktop\\.settings)$" },
    float  = true,
    size   = "1000 800",
    center = true,
})

-- ========================= Layer rules =========================
-- Glass effect for waybar: frost whatever sits behind the bar's translucent
-- pills. Blur is enabled globally in decoration (lua/settings.lua), but that
-- does nothing for layer surfaces without an explicit rule.
--
-- The namespace is each layer surface's own name, NOT the literal string
-- "waybar" -- a bar named "main" produces the namespace "main". The bar calls
-- itself waybar-main and the popup panels (scripts/panelui.py) call themselves
-- waybar-panel, so this one pattern frosts all of them.
--
-- ignore_alpha leaves the fully transparent gaps between pills unblurred, so
-- only the pills themselves frost.
hl.layer_rule({
    name        = "waybar-glass",
    match       = { namespace = "^(waybar-.*)$" },
    blur        = true,
    ignore_alpha = 0.2,
})

-- Same treatment for the launcher, whose surface calls itself plain "wofi".
-- Its card is a much larger sheet than any pill, so without the frost you read
-- whatever web page happens to be underneath it straight through the list.
hl.layer_rule({
    name        = "wofi-glass",
    match       = { namespace = "^(wofi|launcher)$" },   -- launcher: scripts/launcher.py
    blur        = true,
    ignore_alpha = 0.2,
    -- Spotlight: the card pops in and everything behind it dims.
    animation   = "popin 80%",
    dim_around  = true,
})

-- And for mako's notification stack.
--
-- The namespace is "notifications", NOT "mako" -- mako hardcodes it and it has
-- nothing to do with the binary's name. Getting this wrong is silent: the rule
-- simply never matches and the panels render unblurred, which looks like the
-- blur setting is broken rather than like the selector is. `hyprctl layers` is
-- the way to check -- it prints the real namespace of every live surface.
--
-- ignore_alpha is lower here than on the bar because there are no transparent
-- gaps inside a notification to protect -- the whole panel is meant to frost,
-- and 0.2 would start punching holes in the soft edge of the rounded corners.
hl.layer_rule({
    name         = "mako-glass",
    match        = { namespace = "^(notifications)$" },
    blur         = true,
    ignore_alpha = 0.05,
})

-- The theme switch's cross-fade (scripts/theme-fade.py): a still of every
-- screen laid over it while the theme changes underneath, then faded out by
-- the script itself. It has to cover the screen at once, so no pop-in.
hl.layer_rule({
    name    = "theme-fade",
    match   = { namespace = "^(theme-fade)$" },
    no_anim = true,
})

-- Default workspaces per monitor
--
-- persistent = true is what keeps a workspace alive with nothing on it. It used
-- to be waybar's job: the bar drew placeholder pills from its own
-- persistent-workspaces list for workspaces Hyprland had never actually
-- created. The bar now reads workspaces over ext-workspace-v1 (see the waybar
-- config), and that protocol can only report workspaces that really exist -- so
-- the always-there pills have to be real workspaces, declared here.
--
-- Which monitor each one lives on is the rule below it, not waybar's list. The
-- old bar config claimed 1-5 were all on the primary while this config pinned 4 to the second screen;
-- these rules are the ones Hyprland actually obeys.
--
-- default = true is a separate idea from monitor, and only one rule per monitor
-- gets it: it is the workspace that screen lands on when it first comes up. Every
-- monitor now names one explicitly (1 / 4 / 6) instead of only the primary doing so and
-- the other two arriving at 4 and 6 as a side effect of being the lowest-numbered
-- workspace bound to them. Same result today, but it is now stated rather than
-- inferred, so renumbering something above won't quietly change where a screen
-- boots.
--
-- What is NOT available: "starts here but is free to roam." A persistent
-- workspace has to exist even when it is empty, and a workspace that exists is
-- always on exactly one monitor -- so persistence necessarily gives it a home.
-- Dropping `monitor` doesn't buy freedom either, it just makes the home
-- nondeterministic: Hyprland then assigns one at reload time from whatever screen
-- happened to be focused (tested -- workspace 7 with persistent and no monitor
-- was created on the focused screen and thereafter behaved exactly as if pinned there).
-- The only genuinely roaming workspaces are non-persistent ones, and those are
-- the ones that evaporate when empty -- see the note on the ALT+n loop in
-- lua/binds.lua.
-- 1, 2, 3 and 5 live on the primary screen (P, top of this file). 4 lives on
-- the second screen of SCREENS and 6 on the third -- by place in the host
-- file's list, NOT by "whatever is not the primary", so picking another
-- primary in Settings > Screens moves 1/2/3/5 and leaves 4 and 6 where they
-- were. A machine with fewer screens keeps 4 and 6 (persistent, so the bar's
-- pills stay) on the primary, without default = true -- that screen already
-- lands on 1. With no screen known at all (P nil: the first load of a session
-- on a machine with no host file), nothing is pinned; the next reload pins.
local function pin(ws, mon, default)
    local rule = { workspace = ws, persistent = true }
    if mon then
        rule.monitor = mon
        if default then rule.default = true end
    end
    hl.workspace_rule(rule)
end
local second, third = SCREENS[2], SCREENS[3]
pin("1", P, true)
pin("2", P)
pin("3", P)
pin("5", P)
pin("4", second or P, second ~= nil)
pin("6", third or P,  third ~= nil)
