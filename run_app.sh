#!/bin/bash
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_LIBRARY_PATH"
cd "$(dirname "$0")"
exec arch -arm64 venv/bin/python3.14 app.py "$@"