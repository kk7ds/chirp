#!/bin/bash

BASE="$1"
RETCODE=0

RED='\033[1;31m'
GREEN='\033[1;32m'
NC='\033[0m'

function fail() {
    echo -e "${RED}$*${NC}"
    RETCODE=1
}

echo -e "${GREEN}Checking from $(git rev-parse --short ${BASE}):${NC}"
git log --pretty=oneline --no-merges --abbrev-commit ${BASE}..

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

for file in $(git diff --name-only ${BASE}..); do
    if file $file | grep -q CRLF; then
        fail "$file : Files should be LF (Unix) format, not CR (Mac) or CRLF (Windows)"
    fi
done

if git log ${BASE}.. --merges | grep .; then
    fail Please do not include merge commits in your PR
fi

make -C chirp/locale clean all >/dev/null
if git diff chirp/locale | grep '^\+[^#+]' | grep -v POT-Creation; then
    git diff
    fail Locale files need updating
fi

exit $RETCODE
