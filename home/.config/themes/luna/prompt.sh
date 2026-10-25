# ~/.config/themes/luna/prompt.sh -- the bash prompt in the luna theme
# (theme.py writes it to ~/.bashrc.d/theme-prompt.sh; new shells). Fedora's
# PROMPT_* variables, as cyberpunk's prompt.sh explains; ANSI colours, i.e.
# the console-blue palette in theme.conf (term.*): 32 green #5fd35f,
# 34 blue #6fa8ff, 33 yellow #e8c547, 31 red #ff6b6b, 90 bright black
# #8b97b2 (5.2:1 on #012456, the slot kept for hints).
#
#   you on ~/.config/themes  (main)  14:05
#   > $                       after a success: a green >
#   [1] > $                   after a failure: the status in red brackets
#
# Plain ASCII on purpose: a console prompt of the XP era had no symbols, and
# Liberation Mono draws every one of these characters itself.

PROMPT_DIRTRIM=3
PROMPT_START=''
PROMPT_HIGHLIGHT=1
PROMPT_COLOR=32
PROMPT_USERHOST='\u'
PROMPT_SEPARATOR=' \[\e[0;90m\]on\[\e[0m\] '
PROMPT_SEPARATOR_COLOR=''
PROMPT_DIRECTORY='\w${__luna_branch}'
PROMPT_DIR_COLOR='1;34'
PROMPT_END='${__luna_clock}\n${__luna_mood}'

__luna_prompt() {
    local status=$?
    # Real control bytes, not \[ \e \]: bash decodes those escapes BEFORE it
    # expands these variables into the prompt (cyberpunk's prompt.sh, same).
    if [ "$status" -ne 0 ]; then
        __luna_mood=$'\001\e[1;31m\002'"[$status] >"$'\001\e[0m\002 '
    else
        __luna_mood=$'\001\e[1;32m\002>\001\e[0m\002 '
    fi
    # The time, quiet, at the end of the first line: bright black, not SGR 2
    # (dim) -- kitty draws dim at dim_opacity 0.4, which lofi measured at
    # 2.8:1.
    printf -v __luna_clock '  \001\e[0;90m\002%(%H:%M)T\001\e[0m\002' -1
    local branch
    branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
    __luna_branch=${branch:+$'\001\e[0;33m\002'"  ($branch)"$'\001\e[0m\002'}
}
# The branch rides on the directory (PROMPT_DIRECTORY), not in Fedora's
# PROMPT_GIT_BRANCH: its PS1 puts the separator -- " on " here -- before that
# one too, which read "~/dotfiles on (main)" (moe found this first).
case ";${PROMPT_COMMAND};" in
    *";__luna_prompt;"*) ;;
    *) PROMPT_COMMAND="__luna_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
