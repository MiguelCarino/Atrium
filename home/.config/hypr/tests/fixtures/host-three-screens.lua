-- A host file for the tests (tests/helpers.py points HYPR_HOST_FILE here):
-- three screens -- a primary with HDR, a second and a third -- so the
-- scripts' screen logic (scripts/screens.py) answers the same on any
-- machine. Only the two lines screens.py reads matter.
local M = {}
M.hdr_capable = { ["DP-1"] = true }
M.screens = { "DP-1", "DP-2", "HDMI-A-1" }
function M.apply(screen) end
return M
