# Railguard for hand-typed commands (source it from ~/.bashrc; railguard.py's
# docstring has the whole picture). Build tools run in heavy.slice: the
# desktop, games and agent sessions keep priority, and a build that runs out
# of memory dies alone instead of freezing the machine.
#
#     heavy CMD...     run any command there (a render, an encode, a script)
#     command make     skip it for one run
#
# Already in agents.slice or heavy.slice (an agent's command -- its shell
# snapshot carries these functions -- or a build calling make inside make):
# run as is, so nothing escapes the limits it is already under.
heavy() {
    local cg
    read -r cg < /proc/self/cgroup
    case $cg in
        */agents.slice/*|*/heavy.slice/*) command "$@"; return ;;
    esac
    if [ -S "${XDG_RUNTIME_DIR:-/nonexistent}/bus" ] && command -v systemd-run >/dev/null; then
        systemd-run --user --scope --quiet --collect --slice=heavy.slice \
            --description="heavy: $*" choom -n 300 -- "$@"
    else
        command "$@"
    fi
}
for _rg_tool in make ninja cmake meson cargo rpmbuild; do
    eval "$_rg_tool() { heavy $_rg_tool \"\$@\"; }"
done
unset _rg_tool
