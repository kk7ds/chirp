#!/bin/bash

BASE="$1"
RETCODE=0

function fail() {
    echo $*
    RETCODE=1
}

git diff ${BASE}.. '*.py' | grep '^+' > added_lines

if grep -E '(from|import).*six' added_lines; then
    fail No new uses of future
fi

if grep -E '\wsix\w' added_lines; then
    fail No new uses of six
fi

if grep -E '(from|import).*builtins' added_lines; then
    fail No new uses of future
fi

if grep -E '\wfuture\w' added_lines; then
    fail No new uses of future
fi

if grep -E '(from|import).*past' added_lines; then
    fail Use of past library not allowed
fi

if grep -E 'MemoryMap\(' added_lines; then
    fail New uses of MemoryMap should be MemoryMapBytes
fi

for file in $(git diff ${BASE}.. '*.py' | diffstat -l); do
    if grep -qE '\r' $file; then
        fail "$file : Files should be LF (Unix) format, not CR (Mac) or CRLF (Windows)"
    fi
done

exit $RETCODE
