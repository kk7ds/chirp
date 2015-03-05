#!/usr/bin/env bash
# Runs cpep.py with the proper verion of the pep8 library.

PEP8_VERSION="1.6.2"

TOOLS_DIR="$(dirname $0)"
VENV="${TMPDIR:-${TOOLS_DIR}}/cpep8.venv"

virtualenv="$(which virtualenv)"
if [ ! -x "$virtualenv" ]; then
    echo 'Please install virtualenv'
    exit 1
fi
if [ ! -d "$VENV" ]; then
    virtualenv "$VENV"
fi

source ${VENV}/bin/activate
pip install pep8==${PEP8_VERSION} >${VENV}/pep8.log 2>&1
${TOOLS_DIR}/cpep8.py "$@"
deactivate
