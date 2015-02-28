#!/usr/bin/env bash

VENV="${TMPDIR:-/tmp}/venv"

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

function make_supported() {
    ./share/make_supported.py > /dev/null
}

function style_tests() {
    ./tools/checkpatch.sh
}

function ensure_test_venv() {
    virtualenv=$(which virtualenv)
    if [ ! -x "$virtualenv" ]; then
	echo 'Please install virtualenv'
	return 1
    fi
    if [ ! -d "$VENV" ]; then
	virtualenv "$VENV"
    fi
    return 0
}

function pep8() {
    ensure_test_venv
    if [ $? -ne 0 ]; then
	record_failure pep8
	return
    fi
    source ${VENV}/bin/activate
    pip install pep8==1.4.6 >${VENV}/pep8.log 2>&1
    echo "Checking for PEP8 regressions..."
    time ./tools/cpep8.py
    deactivate
}

if test -z "${TESTS[*]}"; then
    TESTS=( unit_tests driver_tests make_supported style_tests pep8 )
fi
for testname in "${TESTS[@]}"; do
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
