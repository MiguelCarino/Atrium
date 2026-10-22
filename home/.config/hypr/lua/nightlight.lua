-- ~/.config/hypr/lua/nightlight.lua
-- Loaded from ~/.config/hypr/hyprland.lua (the index). Only the timers that
-- run scripts/nightlight.sh; the SUPER+N bind is in lua/binds.lua.

---@module 'hl'

-- ========================= Night light =========================
-- Warm screens in the evening (20:00 to 07:00 unless changed). All the logic
-- -- schedule, override, backend choice, the shader itself -- lives in
-- scripts/nightlight.sh; this block only decides WHEN it runs. The times,
-- the temperature and auto / always on / off are Settings > Screens > Night
-- light (nightlight.sh mode / start / end / temp), kept in
-- ~/.local/state/hypr/nightlight.conf and read by the script on every tick,
-- so changing them needs no reload; the defaults are at the top of the
-- script, not here, so the schedule has exactly one home.
--
-- Backend: hyprsunset (CTM, free) when installed, otherwise
-- decoration.screen_shader (a warm GLSL pass, works with nothing installed).
-- Not set anywhere in the config on purpose: the shader is applied at runtime
-- with hl.config, so a `hyprctl reload` -- which gamemode OFF does -- clears
-- it. The oneshot below is what puts it back.
--
-- Two timers rather than an hl.on("hyprland.start"):
--   * oneshot, 3s after the config is (re)loaded: covers both login and every
--     reload, with no reliance on which events fire on a reload. The delay
--     gives hyprctl's socket time to answer at login.
--   * repeat, every 5 min: crosses the 20:00/07:00 boundaries, and expires a
--     manual SUPER+N override when its boundary passes. 5 min is the worst
--     case lateness; the script is a few hyprctl calls and does nothing when
--     the screen is already right, so a shorter period would only add churn.
-- hl.timer's timeout is in milliseconds (verified: a 1500 oneshot fired
-- ~1.5s later). Both are kept in a global, not a local: nothing in the config
-- would otherwise reference them after load, and an unreferenced userdata is
-- fair game for the Lua GC. The global also gives you a handle:
--   hyprctl eval 'nightlight_timers.tick:set_enabled(false)'
-- pauses the schedule until the next reload.
--
-- A reload DOES start from a fresh Lua state -- verified during the module
-- split (Oct 2026): a global set with `hyprctl eval` was nil after `hyprctl
-- reload`. So today nightlight_timers is always nil here and this guard is a
-- no-op. It stays as insurance in case that ever changes: if the state were
-- kept, the previous load's timers would still be alive and in this global,
-- and without switching them off every reload would add another 5-minute
-- ticker. Measured Oct 2026: timers from the old state also stop firing
-- after `hyprctl reload` (a 2 s repeat timer stopped at the reload; a 4 s
-- oneshot created 0.5 s before a reload never fired), so they do not stack;
-- the guard is pure insurance.
if nightlight_timers then
    for _, t in pairs(nightlight_timers) do t:set_enabled(false) end
end
nightlight_timers = {
    boot = hl.timer(function() hl.exec_cmd("~/.config/hypr/scripts/nightlight.sh auto") end,
        { timeout = 3000, type = "oneshot" }),
    tick = hl.timer(function() hl.exec_cmd("~/.config/hypr/scripts/nightlight.sh auto") end,
        { timeout = 300000, type = "repeat" }),
}
