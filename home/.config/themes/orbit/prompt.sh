# ~/.config/themes/orbit/prompt.sh -- the bash prompt in the orbit theme
# (theme.py writes it to ~/.bashrc.d/theme-prompt.sh; new shells). Fedora's
# PROMPT_* variables, as cyberpunk's prompt.sh explains; ANSI colours, i.e.
# the console palette in theme.conf (term.*), measured on the floor #070b14:
# 36 teal #5cc8db 10.1:1, 37 console white #c9d3e0 13.0, 34 blue #6aa7ff
# 8.1, 31 red #f0565a 5.8, 90 bright black #7a8aa4 5.6 (the slot kept for
# hints).
#
#   T+00:42  you  ~/.config/themes  ⎇ main
#   ▸ $                        after a success: the teal ▸
#   NO-GO 1 ▸ $                after a failure: the status, in red
#
# T+ is mission elapsed time: how long THIS shell has been open (bash's
# $SECONDS), hours:minutes -- a console clock that means something per
# window. No colour emoji: COSMIC Terminal has no colour-emoji fallback
# (blank). ▸ and ⎇ are single-width; JetBrains Mono draws ▸ itself, and
# fontconfig's fallback (DejaVu Sans) draws ⎇.

PROMPT_DIRTRIM=3
PROMPT_START='${__orbit_met}'
PROMPT_HIGHLIGHT=1
PROMPT_COLOR=37
PROMPT_USERHOST='\u'
PROMPT_SEPARATOR='  '
PROMPT_SEPARATOR_COLOR=''
PROMPT_DIRECTORY='\w${__orbit_branch}'
PROMPT_DIR_COLOR='1;36'
PROMPT_END='\n${__orbit_mood}\[\e[1;36m\]▸\[\e[0m\] '

__orbit_prompt() {
    local status=$?
    # Real control bytes, not \[ \e \]: bash decodes those escapes BEFORE it
    # expands these variables into the prompt (cyberpunk's prompt.sh, same).
    if [ "$status" -ne 0 ]; then
        __orbit_mood=$'\001\e[1;31m\002'"NO-GO $status "$'\001\e[0m\002'
    else
        __orbit_mood=''
    fi
    # The elapsed time, quiet, at the start of the first line: bright black,
    # not SGR 2 (dim) -- kitty draws dim at dim_opacity 0.4, which lofi
    # measured at 2.8:1.
    printf -v __orbit_met '\001\e[0;90m\002T+%02d:%02d\001\e[0m\002  ' \
        $((SECONDS / 3600)) $((SECONDS / 60 % 60))
    local branch
    branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
    __orbit_branch=${branch:+$'\001\e[0;34m\002'"  ⎇ $branch"$'\001\e[0m\002'}
}
# The branch rides on the directory (PROMPT_DIRECTORY), not in Fedora's
# PROMPT_GIT_BRANCH: its PS1 puts the separator before that one too (moe
# found this first).
case ";${PROMPT_COMMAND};" in
    *";__orbit_prompt;"*) ;;
    *) PROMPT_COMMAND="__orbit_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
