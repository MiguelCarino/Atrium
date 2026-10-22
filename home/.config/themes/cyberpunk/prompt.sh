# ~/.config/themes/cyberpunk/prompt.sh -- the bash prompt in the cyberpunk
# theme. theme.py writes it to ~/.bashrc.d/theme-prompt.sh (~/.bashrc sources
# ~/.bashrc.d/*), so it takes effect in shells opened after a theme switch.
#
# It only sets the variables of Fedora's own prompt (/etc/profile.d/
# bash-color-prompt.sh builds PS1 from PROMPT_START, PROMPT_COLOR, ...), so
# nothing here replaces that machinery. Colours are ANSI SGR numbers, i.e.
# the TERMINAL'S palette (term.* in theme.conf): 36 cyan #00f0ff, 31 the
# neon pink-magenta #ff2a6d, 33 yellow, 90 the dim grey.
#
#   ╭─[you@desktop]─[~/.config/themes]─[⎇ main]
#   ╰─✗ 1 ▶ $          (the ✗ only after a command that failed)

PROMPT_DIRTRIM=3
PROMPT_START='\[\e[36m\]╭─['
PROMPT_HIGHLIGHT=1
PROMPT_COLOR=31
PROMPT_USERHOST='\u@\h'
PROMPT_SEPARATOR=']─['
PROMPT_SEPARATOR_COLOR=36
PROMPT_DIRECTORY='\w'
PROMPT_DIR_COLOR='1;36'
PROMPT_GIT_COLOR=33
PROMPT_END='\[\e[36m\]]\n╰─${__cp_fail}\[\e[36m\]▶\[\e[0m\] '

# Before each prompt: the last command's status (first, before anything
# overwrites $?) and the git branch -- empty outside a repository, so the
# prompt then has no empty "[]" for it.
__cp_prompt() {
    local status=$?
    if [ "$status" -ne 0 ]; then
        # Real control bytes, not \[ \e \]: bash decodes those escapes
        # BEFORE it expands ${__cp_fail} into the prompt, so they would show
        # literally. \001 / \002 are what \[ and \] turn into.
        __cp_fail=$'\001\e[1;31m\002'"✗ $status "$'\001\e[0m\002'
    else
        __cp_fail=""
    fi
    local branch
    branch=$(git symbolic-ref --short -q HEAD 2>/dev/null || git rev-parse --short HEAD 2>/dev/null)
    PROMPT_GIT_BRANCH=${branch:+⎇ $branch}
}
case ";${PROMPT_COMMAND};" in
    *";__cp_prompt;"*) ;;
    *) PROMPT_COMMAND="__cp_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;
esac
