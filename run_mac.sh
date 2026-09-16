#!/usr/bin/env bash
# macOS launch script. Run from the repo root.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

# launcher.py installs the optional add-ons (transcription history), the same
# way run.bat does on Windows.
exec ./.venv/bin/python launcher.py
