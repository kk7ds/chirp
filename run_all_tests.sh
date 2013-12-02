#!/bin/bash

function record_failure() {
    FAILED="$1 $FAILED"
}

function unit_tests() {
    NOSE=$(which nosetests)
    if [ -x "$NOSE" ]; then
	$NOSE -v tests/unit
    else
	echo "NOTE: nosetests required for unit tests!"
	record_failure unit_tests
    fi
}

function driver_tests() {
    (cd tests && ./run_tests)
}

function style_tests() {
    ./tools/checkpatch.sh
}

TESTS="unit_tests driver_tests style_tests"
for testname in $TESTS; do
    eval "$testname" || record_failure "$testname"
done

echo "================================================"

if [ -z "$FAILED" ]; then
    echo Tests OK
else
    failed=$(echo $FAILED | sed 's/ /, /g' | sed 's/_/ /g')
    echo Tests FAILED: $failed
    exit 1
fi
