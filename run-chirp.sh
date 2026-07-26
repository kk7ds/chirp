#!/bin/bash
# Runs CHIRP from this git checkout using the local .venv.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"

if [ ! -d .venv ]; then
    echo "Creating venv (with access to system wxPython)..." >&2
    python3 -m venv --system-site-packages .venv
    .venv/bin/pip install -e .
fi

exec .venv/bin/python chirpwx.py "$@"
