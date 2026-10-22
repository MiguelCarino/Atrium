#!/usr/bin/env bash
# The desktop scripts' tests (stdlib unittest; ~/.config/hypr/tests/test_*.py).
# Quiet when everything passes, the failures and exit 1 when not.
#
#   run.sh          all of them
#   run.sh -v       verbose
#
# Hermetic: helpers.py points XDG_STATE_HOME / XDG_CACHE_HOME /
# XDG_RUNTIME_DIR at a scratch folder before any script is imported, and the
# tests stub every call that would reach the screens or the services.
cd "$(dirname "$(readlink -f "$0")")" || exit 2
verbosity=1; [[ ${1:-} == -v ]] && verbosity=2
out=$(PYTHONDONTWRITEBYTECODE=1 python3 -W ignore -m unittest discover -s . -p 'test_*.py' -v 2>&1); rc=$?
if (( rc != 0 )) || (( verbosity == 2 )); then
    printf '%s\n' "$out"
fi
exit $rc
