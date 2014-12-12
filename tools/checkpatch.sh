#!/usr/bin/env bash
#
# CHIRP coding standards compliance script
#
# To add a test to this file, create a new check_foo() function
# and then add it to the list of TESTS= below
#

TESTS="check_long_lines check_bug_number check_commit_message_line_length"

function check_long_lines() {
    local rev="$1"
    local files="$2"

    # For now, ignore this check on chirp/
    files=$(echo $files | sed -r 's#\bchirp[^ ]*\b##')

    if [ -z "$files" ]; then
        return
    fi

    pep8 --select=E501 $files || \
        error "Please use <80 columns in source files"
}

function check_bug_number() {
    local rev="$1"
    hg log -vr $rev | grep -qE '#[0-9]+' || \
        error "A bug number is required like #123"
}

function _less_than_80() {
    while true; do
        read line
        if [ -z "$line" ]; then
            break
        elif [ $(echo -n "$line" | wc -c) -ge 80 ]; then
            return 1
        fi
    done
}

function check_commit_message_line_length() {
    local rev="$1"
    hg log -vr $rev | (_less_than_80) || \
        error "Please keep commit message lines to <80 columns"
}

# --- END OF TEST FUNCTIONS ---

function error() {
    echo FAIL: $*
    ERROR=1
}

function get_touched_files() {
    local rev="$1"
    hg status -n --change $rev | grep '\.py$'
}

rev=${1:-tip}
files=$(get_touched_files $rev)

for testname in $TESTS; do
    eval "$testname $rev \"$files\""
done

if [ -z "$ERROR" ]; then
    echo "Patch '${rev}' is OK"
else
    exit 1
fi
