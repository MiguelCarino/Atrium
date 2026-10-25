# ~/.config/themes/seasons/prompt.sh -- the bash prompt in the seasons theme
# (theme.py writes it to ~/.bashrc.d/theme-prompt.sh, with the season's
# season/<s>/prompt.sh appended; new shells). Fedora's PROMPT_* variables,
# as cyberpunk's prompt.sh explains. An almanac's line:
#
#   ✿ 24 Oct  you  ~/.config/themes  ⎇ main
#   › $                        after a success
#   exit 1 › $                 after a failure: the status, in red
#
# The mark and its colour are the season's (__seasons_glyph, __seasons_hue,
# set by the season file appended after this one; the defaults below are
# what a shell shows without it). ANSI colours only: the terminal palette
# (term.* in season/<s>/theme.conf) carries the season, so this file is the
# same all year. Measured on each season's floor, spring / summer / autumn
# / winter: 37 (white, the user) 11.1 / 12.3 / 11.2 / 12.2, 36 (cyan, the
# branch) 10.5 / 10.4 / 9.8 / 12.0, 31 (red, a failure) 6.7 / 6.5 / 6.3 /
# 6.7, 90 (bright black, the date) 6.6 / 5.9 / 5.1 / 5.6; the season's mark
# in season/<s>/prompt.sh. The directory is bold in the mark's colour.
#
# The date is today's, day and short month (LC_TIME's names), from bash's
# own printf -- no process per prompt. No colour emoji: COSMIC Terminal has
# no colour-emoji fallback (blank). The marks are single-width and in a mono
# face (Adwaita Mono; ☼ in Source Code Pro itself), and none of them is in
# Noto Color Emoji; › is in Source Code Pro, ⎇ in Adwaita Mono.

__seasons_glyph='*'
__seasons_hue='33'

PROMPT_DIRTRIM=3
PROMPT_START='${__seasons_mark}'
PROMPT_HIGHLIGHT=0
PROMPT_COLOR=37
PROMPT_USERHOST='\u'
PROMPT_SEPARATOR='  '
PROMPT_SEPARATOR_COLOR=''
PROMPT_DIRECTORY='\w${__seasons_branch}'
PROMPT_DIR_COLOR="1;${__seasons_hue}"
PROMPT_END='\n${__seasons_mood}${__seasons_end}'

__seasons_prompt() {
    local status=$?
    # Real control bytes, not \[ \e \]: bash decodes those escapes BEFORE it
    # expands these variables into the prompt (cyberpunk's prompt.sh, same).
    if [ "$status" -ne 0 ]; then
        __seasons_mood=$'\001\e[0;31m\002'"exit $status "$'\001\e[0m\002'
    else
        __seasons_mood=''
    fi
    # The date quiet, bright black -- not SGR 2 (dim): kitty draws dim at
    # dim_opacity 0.4, which lofi measured at 2.8:1.
    local today
    printf -v today '%(%-d %b)T' -1
    __seasons_mark=$'\001\e[1;'"${__seasons_hue}"$'m\002'"${__seasons_glyph}"$'\001\e[0;90m\002'" ${today}"$'\001\e[0m\002  '
    __seasons_end=$'\001\e[1;'"${__seasons_hue}"$'m\002›\001\e[0m\002 '
    # Fedora's PS1 reads PROMPT_DIR_COLOR as a bare SGR number at each
    # prompt (no expansion inside it), so it is set here, after the season
    # file has had its say.
    PROMPT_DIR_COLOR="1;${__seasons_hue}"
    local branch
    branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
    __seasons_branch=${branch:+$'\001\e[0;36m\002'"  ⎇ $branch"$'\001\e[0m\002'}
}
# The branch rides on the directory (PROMPT_DIRECTORY), not in Fedora's
# PROMPT_GIT_BRANCH: its PS1 puts the separator before that one too (moe
# found this first).
case ";${PROMPT_COMMAND};" in
    *";__seasons_prompt;"*) ;;
    *) PROMPT_COMMAND="__seasons_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
