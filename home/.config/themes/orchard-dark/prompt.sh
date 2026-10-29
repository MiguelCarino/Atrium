# ~/.config/themes/orchard-dark/prompt.sh -- the bash prompt in the
# orchard-dark theme (theme.py writes it to ~/.bashrc.d/theme-prompt.sh; new
# shells). The same prompt as orchard/prompt.sh (prompt files do not
# inherit, so it is repeated here).
#
# The default prompt of the desktop this theme is modelled on, whose shell
# is zsh: user@host, the current folder's own name ("~" at home), then "%"
# (or "#" for root), plain and uncoloured -- only the host is dimmed, in
# ANSI 90 (bright black #4f4f54, 4.7:1 on the terminal's page #c4c4c9;
# orchard-dark's #666666 is 2.9:1 on #1e1e1e, a quiet grey on purpose):
#
#   you@desktop themes %
#
# Fedora's PROMPT_* variables (cyberpunk's prompt.sh explains them) cannot
# draw it: the PS1 they build ALWAYS ends in "\$", so a "%" could only come
# out as "% $". So this file sets PS1 itself, after the system's
# (/etc/bashrc runs bash-color-prompt.sh before ~/.bashrc.d is read). The
# PROMPT_* values are still set, to the same look, for anything that calls
# prompt_setup_color_ps1 again. A theme switch reaches new shells only, as
# with every theme's prompt.

PROMPT_DIRTRIM=1
PROMPT_START=''
PROMPT_HIGHLIGHT=''
PROMPT_COLOR=''
PROMPT_USERHOST='\u@\h'
PROMPT_SEPARATOR=' '
PROMPT_SEPARATOR_COLOR=''
PROMPT_DIRECTORY='\W'
PROMPT_DIR_COLOR=''
PROMPT_GIT_COLOR=''
PROMPT_END=''

__orchard_sym='%'
[ "${EUID:-1}" -eq 0 ] && __orchard_sym='#'
PS1="\u@\[\e[90m\]\h\[\e[0m\] \W ${__orchard_sym} "
unset __orchard_sym
