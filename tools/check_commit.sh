#!/bin/bash

BASE="$1"

function fail() {
    echo $*
    exit 1
}

git diff ${BASE}..HEAD '*.py' | grep '^+' > added_lines

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
