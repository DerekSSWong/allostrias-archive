#!/usr/bin/env bash
# Run every gate and EXIT NON-ZERO if any fails.
#
# This exists because a `for t in tests/*.py; do ...; done` loop always exits
# 0 -- the last `echo` succeeds whatever the test did -- so `run && git commit`
# committed twice over failing gates. The failure has to reach the exit code
# or it does not reach anything.
cd "$(dirname "$0")" || exit 1
failed=0
for t in tests/*.py; do
    # `_name.py` is a helper the gates import, not a gate.
    case "$(basename "$t")" in _*) continue ;; esac
    printf '%-24s ' "$(basename "$t")"
    if timeout 900 python3 "$t" >/dev/null 2>&1; then
        echo PASS
    else
        echo FAIL
        failed=1
    fi
done
[ "$failed" -eq 0 ] && echo "all gates pass" || echo "SOME GATES FAILED"
exit "$failed"
