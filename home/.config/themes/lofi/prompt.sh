# ~/.config/themes/lofi/prompt.sh -- the bash prompt in the lofi theme
# (theme.py writes it to ~/.bashrc.d/theme-prompt.sh; new shells). Fedora's
# PROMPT_* variables, as cyberpunk's prompt.sh explains; ANSI colours, i.e.
# the terminal's dusk palette (term.* in theme.conf): 35 lilac #c7a2e6,
# 36 teal #86c9c4, 33 honey #e9cf7e, 31 berry #ec8a9a, 37 cream #d9ccbc.
# The peach lamp is not an ANSI slot (the 16 colours are the terminal's), so
# the ☾ and the › are written in truecolour, 38;2;242;164;119 = #f2a477:
# kitty and COSMIC Terminal both draw it.
#
#   ☾ you in ~/.config/themes  ♫ main                  21:05
#   ∿ › $                      after a success: a little sound wave
#   (=˘︿˘=) 1 › $              after a failure: a grumpy cat and the status
#
# No colour emoji: COSMIC Terminal has no colour-emoji fallback (blank). ☾, ♫
# and ∿ are single-width; Nunito and Rec Mono Casual lack them, so the IBM
# Plex / system fallback draws them.

PROMPT_DIRTRIM=3
PROMPT_START='\[\e[0;38;2;242;164;119m\]☾\[\e[0m\] '
PROMPT_HIGHLIGHT=1
PROMPT_COLOR=37
PROMPT_USERHOST='\u'
PROMPT_SEPARATOR=' \[\e[0;35m\]in\[\e[0m\] '
PROMPT_SEPARATOR_COLOR=''
PROMPT_DIRECTORY='\w${__lofi_branch}'
PROMPT_DIR_COLOR='1;36'
PROMPT_END='${__lofi_clock}\n${__lofi_mood}\[\e[1;38;2;242;164;119m\]›\[\e[0m\] '

__lofi_prompt() {
    local status=$?
    # Real control bytes, not \[ \e \]: bash decodes those escapes BEFORE it
    # expands these variables into the prompt (cyberpunk's prompt.sh, same).
    if [ "$status" -ne 0 ]; then
        __lofi_mood=$'\001\e[0;31m\002'"(=˘︿˘=) $status "$'\001\e[0m\002'
    else
        __lofi_mood=$'\001\e[0;33m\002∿ \001\e[0m\002'
    fi
    # The time, quiet, at the end of the first line: bright black (#8a80a6,
    # 4.7:1), the palette slot theme.conf keeps for hints. Not SGR 2 (dim):
    # kitty draws dim at dim_opacity 0.4, which put the clock at 2.8:1.
    printf -v __lofi_clock '  \001\e[0;90m\002%(%H:%M)T\001\e[0m\002' -1
    local branch
    branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
    __lofi_branch=${branch:+$'\001\e[0;35m\002'"  ♫ $branch"$'\001\e[0m\002'}
}
# The branch rides on the directory (PROMPT_DIRECTORY), not in Fedora's
# PROMPT_GIT_BRANCH: its PS1 puts the separator -- " in " here -- before that
# one too, which read "~/dotfiles in ♫ main" (moe found this first).
case ";${PROMPT_COMMAND};" in
    *";__lofi_prompt;"*) ;;
    *) PROMPT_COMMAND="__lofi_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
