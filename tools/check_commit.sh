#!/bin/bash

BASE=${1:-origin/master}
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
echo

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

if grep -E '(from|import).*past(?!e)' added_lines; then
    fail Use of past library not allowed
fi

if grep -E 'MemoryMap\(' added_lines; then
    fail New uses of MemoryMap should be MemoryMapBytes
fi

if grep -E "[^_]_\([^\"']" added_lines; then
    fail 'Translated strings must be literals!'
fi

if grep -E "eval\(" added_lines; then
    fail 'Use of eval() is dangerous and not permitted!'
fi

if git diff ${BASE}.. 'tools/cpep8.manifest' | tail -n +5 | grep -q '^+'; then
    fail 'Do not add new files to cpep8.manifest; no longer needed'
fi

if git diff ${BASE}.. 'tools/cpep8.blacklist' | tail -n +5 | grep -q '^+'; then
    fail 'Do not add new files to cpep8.blacklist; fix the code'
fi

grep -i 'license' added_lines > license_lines
if grep -ivE '(GNU General Public License|Free Software Foundation|gnu.org.licenses)' license_lines; then
    fail 'Files must be GPLv3 licensed (or not contain any license language)'
fi

for file in $(git diff --name-only ${BASE}..); do
    if file $file | grep -q CRLF; then
        fail "$file : Files should be LF (Unix) format, not CR (Mac) or CRLF (Windows)"
    fi
done

#if grep 'def match_model' added_lines; then
#    fail 'New drivers should not have match_model() implemented as it is not needed'
#fi

if git log ${BASE}.. --merges | grep .; then
    fail Please do not include merge commits in your PR
fi

make -C chirp/locale clean all >/dev/null 2>&1
if git diff chirp/locale | grep '^+[^#+]' | grep -v POT-Creation; then
    fail Locale files need updating
fi

added_files=$(git diff --name-only --diff-filter=A ${BASE}..)
added_py=$(git diff --name-only --diff-filter=A ${BASE}.. | grep '\.py$')
if echo $added_py | grep -q chirp.drivers && ! echo $added_files | grep -q tests.images; then
    fail All new drivers should include a test image
fi

existing_drivers=$(git ls-tree --name-only $BASE chirp/drivers/)
limit=51
for nf in $added_py; do
    for of in $existing_drivers; do
        common=$(wdiff -s $of $nf | grep -I $nf | sed -r 's/.* ([0-9]+)% common.*/\1/')
        if [ ! "$common" ]; then
            continue
        fi
        if [ "$common" -gt "$limit" ]; then
            fail "New file $nf shares at least ${common}% with $of!"
        fi
    done
done

rm -f added_lines license_lines

exit $RETCODE
