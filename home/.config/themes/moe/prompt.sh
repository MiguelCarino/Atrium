# ~/.config/themes/moe/prompt.sh -- the bash prompt in the moe theme
# (theme.py writes it to ~/.bashrc.d/theme-prompt.sh; new shells). Fedora's
# PROMPT_* variables, as cyberpunk's prompt.sh explains; ANSI colours, i.e.
# the terminal's sakura-night palette: 31 sakura pink #ff7a9c, 35 lavender
# #d8a6f0, 36 mint-sky #8fe3e0, 33 lemon, 32 mint.
#
#   ✿ you in ~/.config/themes  ♡ main                  21時05分
#   ❯ $                       after a success: ✧ before the ❯
#   (｡•́︿•̀｡) 1 ❯ $            after a failure: a sad face and the status

PROMPT_DIRTRIM=3
# ✿, not the 🌸 emoji: COSMIC Terminal has no colour-emoji fallback (blank).
PROMPT_START='\[\e[0;31m\]✿\[\e[0m\] '
PROMPT_HIGHLIGHT=1
PROMPT_COLOR=31
PROMPT_USERHOST='\u'
PROMPT_SEPARATOR=' \[\e[0;35m\]in\[\e[0m\] '
PROMPT_SEPARATOR_COLOR=''
PROMPT_DIRECTORY='\w${__moe_branch}'
PROMPT_DIR_COLOR='1;36'
PROMPT_END='${__moe_clock}\n${__moe_mood}\[\e[1;31m\]❯\[\e[0m\] '

__moe_prompt() {
    local status=$?
    # Real control bytes, not \[ \e \]: bash decodes those escapes BEFORE it
    # expands these variables into the prompt (cyberpunk's prompt.sh, same).
    if [ "$status" -ne 0 ]; then
        __moe_mood=$'\001\e[0;35m\002'"(｡•́︿•̀｡) $status "$'\001\e[0m\002'
    else
        __moe_mood=$'\001\e[0;33m\002✧ \001\e[0m\002'
    fi
    # The time as Japanese writes it, dim, at the end of the first line.
    printf -v __moe_clock '  \001\e[2;37m\002%(%-H時%M分)T\001\e[0m\002' -1
    local branch
    branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
    __moe_branch=${branch:+$'\001\e[0;35m\002'"  ♡ $branch"$'\001\e[0m\002'}
}
# The branch rides on the directory (PROMPT_DIRECTORY), not in Fedora's
# PROMPT_GIT_BRANCH: its PS1 puts the separator -- " in " here -- before that
# one too, which read "~/dotfiles in ♡ main".
case ";${PROMPT_COMMAND};" in
    *";__moe_prompt;"*) ;;
    *) PROMPT_COMMAND="__moe_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
