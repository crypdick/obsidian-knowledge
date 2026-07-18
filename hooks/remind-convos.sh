#!/usr/bin/env bash
# Compatibility shim: remind-convos.py delegates to capture-session.py.
# Existing sessions may have cached the old manifest pointing at this .sh
# path; this shim forwards to the Python implementation so they keep
# working until the plugin manifest reloads.
exec python3 "$(dirname "$0")/remind-convos.py"
