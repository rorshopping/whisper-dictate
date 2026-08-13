#!/usr/bin/env bash
# macOS launch script. Run from the repo root.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi

./.venv/bin/python main.py
