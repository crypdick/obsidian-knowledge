#!/usr/bin/env bash
# Compatibility shim: the real hook is now remind-convos.py (v1.2.0+).
# Existing sessions may have cached the old manifest pointing at this .sh
# path; this shim forwards to the Python implementation so they keep
# working until the plugin manifest reloads.
exec python3 "$(dirname "$0")/remind-convos.py"
