#!/usr/bin/env bash
# macOS launch script. Run from the repo root.
set -e
cd "$(dirname "$0")"

# First run: let the platform-aware installer build the virtualenv.
if [ ! -d .venv ]; then
  python3 install.py --platform macos
fi

# One-shot flags must run main.py directly: launcher.py always starts the app.
# The self-check needs none of the macOS patches (no GUI, no paste).
case "${1:-}" in
  --doctor|--help|-h)
    exec ./.venv/bin/python main.py "$@"
    ;;
esac

# launcher.py applies the macOS platform patches (platform_mac.py) and installs
# the optional add-ons (transcription history) - the same entry point run.bat
# uses on Windows. Starting main.py directly on macOS skips the patches.
exec ./.venv/bin/python launcher.py "$@"
