#!/usr/bin/env bash
# Restart waybar by ending the process and starting a fresh one -- through its
# systemd user unit since 2026-10. This replaces `pkill -SIGUSR2 waybar` (the
# old ALT+G), which reloaded it in place.
#
# Why SIGUSR2 is not used: waybar 0.15.0 (Fedora 44) handles SIGUSR2 by
# destroying every module and building them again in the same process.
# Destroying a module stops its worker thread with pthread_cancel
# (util/sleeper_thread.hpp, SleeperThread::stop). If that cancel arrives while
# a custom-module worker is inside fork() (util/command.hpp, command::open),
# then:
#   - the child inherits the pending cancel. It is cancelled at its first
#     cancellation point, before execlp, so it never becomes /bin/sh. It
#     unwinds, glibc's start_thread calls exit(0), and the static
#     hyprland::IPC singleton is destroyed. ~IPC returns early in any pid other
#     than its owner, but its std::thread member is still joinable, so
#     std::terminate runs: SIGABRT and a coredump named "waybar".
#   - the parent thread is cancelled before it reaches waitpid, so no one
#     reaps the child and it stays a zombie under waybar until waybar exits.
# The coredump stacks show exactly this sequence:
#   start_thread -> exit -> __run_exit_handlers -> hyprland::IPC::~IPC.cold
#   -> std::terminate
# SIGINT goes through the same teardown (Client::reset) and has the same
# problem.
#
# SIGTERM does not. waybar installs no handler for it, so the kernel ends the
# process at once: no destructors, no pthread_cancel, no fork race. Module
# scripts started with "exec" have PR_SET_PDEATHSIG=SIGTERM and exit along
# with it -- but only those direct children. Anything a module script starts
# itself (playerctl --follow under player.py, pactl subscribe under
# privacy.py) is a grandchild with no PDEATHSIG; under the systemd unit the
# stop signal goes to the whole cgroup, so those go too. Zombies left by earlier SIGUSR2 reloads are reparented and reaped
# when the old waybar exits. Apps started from on-click (kitty, pavucontrol)
# do not set PDEATHSIG and keep running, which is what we want.
#
# The toolbox section (waybar-toolbox.service) is PartOf waybar.service, so
# the restart below takes it down and brings it back (hidden) as well.
#
# Bound to ALT+G in ~/.config/hypr/lua/binds.lua ("Bar: Restart bar").

set -u

HERE=$(dirname "$(readlink -f "$0")")
RUNTIME=${XDG_RUNTIME_DIR:-/tmp}

note() {
    # The bar is the usual place for status, and it is the thing being
    # restarted, so problems are reported through mako instead.
    notify-send -a "Waybar" -u "${2:-normal}" "Bar restart" "$1" 2>/dev/null || true
}

# Pressing ALT+G twice quickly (or running this from a terminal while the
# bind fires) would start two kill-and-start sequences, and the second would
# kill the waybar the first just started. (Holding the key does not repeat:
# the bind has repeat=false.) -n: a second run while one is in progress does
# nothing.
exec 9>"$RUNTIME/waybar-restart.lock"
flock -n 9 || exit 0

# 1. Close the popup panels. They are separate processes (scripts/panel.py),
#    each positioned under the bar pill that opened it. Once the bar is gone
#    the pill is gone too, and the panel is left in place with nothing under
#    it.
python3 "$HERE/panel.py" close-all 2>/dev/null || true

# 2. Restart the systemd unit (Fedora's waybar.service, enabled; local
#    tweaks in ~/.config/systemd/user/waybar.service.d/hyprland.conf). systemd
#    stops it with SIGTERM to the whole cgroup -- the safe signal, see above,
#    and it also takes the module scripts' grandchildren with it -- escalates
#    to SIGKILL after 3 s (TimeoutStopSec), then starts a fresh one.
#    9>&- keeps the lock fd away from systemctl (harmless, but tidy).
if ! systemctl --user restart waybar.service 9>&-; then
    note "systemctl --user restart waybar failed. See: journalctl --user -u waybar" critical
    exit 1
fi

# 3. Check it is still up a moment later. A bad config makes waybar start and
#    exit within a second, which `restart` alone does not report; the unit
#    then retries on its own (Restart=always) until its start limit.
sleep 1.5
if ! systemctl --user is-active --quiet waybar.service; then
    note "waybar did not stay up -- usually a config error. See: journalctl --user -u waybar" critical
    exit 1
fi
exit 0
