#!/usr/bin/env bash
# Convenience wrapper only - all startup logic lives in run_meetnote.py.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/run_meetnote.py" "$@"
