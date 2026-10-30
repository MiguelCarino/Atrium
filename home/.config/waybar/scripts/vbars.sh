# Vertical meters for the bar's pills on a narrow screen -- sourced by
# cpu_usage.sh and gpu_usage.sh; barfit.py vbars() draws the same markup for
# the Python pills (tests/test_bar_pills.py holds the two equal).
#
# A meter is 4 segments of 25%, stacked bottom up: four short lines of Pango
# markup in one label, each segment a pair of lower-half blocks (the empty
# upper half is the gap between two segments). Lit: the pill's colour; unlit:
# the same colour, faint. A value above 0 always lights the first segment,
# so 3% does not read as nothing. Builtins only: no fork per tick.

VB_SEG=$'▄▄'          # ▄▄
VB_FAINT=28%
VB_OPEN="<span font_family='monospace' size='4000' line_height='0.75'>"

# vb_count <percent> <var>: how many of the 4 segments are lit, into var.
vb_count() {
    local vb_v=${1%%.*}
    [[ $vb_v =~ ^[0-9]+$ ]] || vb_v=0
    (( vb_v > 100 )) && vb_v=100
    printf -v "$2" '%d' $(( (vb_v + 24) / 25 ))
}

# vbars <colour> <var> <percent>...: one meter per percent, side by side,
# into var.
vbars() {
    # vb_* names only: printf -v into the caller's variable must not land in
    # a local of the same name here.
    local vb_colour=$1 vb_out=$2 vb_row vb_k vb_n vb_text="$VB_OPEN" vb_sep
    shift 2
    local -a vb_lit=()
    for vb_k in "$@"; do vb_count "$vb_k" vb_n; vb_lit+=("$vb_n"); done
    for vb_row in 4 3 2 1; do
        vb_sep=""
        for vb_n in "${vb_lit[@]}"; do
            if (( vb_n >= vb_row )); then
                vb_text+="$vb_sep<span color='$vb_colour'>$VB_SEG</span>"
            else
                vb_text+="$vb_sep<span color='$vb_colour' fgalpha='$VB_FAINT'>$VB_SEG</span>"
            fi
            vb_sep=" "
        done
        (( vb_row > 1 )) && vb_text+='\n'
    done
    printf -v "$vb_out" '%s' "$vb_text</span>"
}
