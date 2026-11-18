#!/usr/bin/env bash
# MorseWire install: project-level Python tooling only.
# Never uses sudo/apt/system packages, never starts the app, and exits 0.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "error: $PYTHON not found — install Python 3.8+ first (see INSTALL.md)" >&2
  exit 1
fi

"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else "MorseWire needs Python 3.8 or newer")'

echo "[1/4] upgrading pip, setuptools and wheel"
"$PYTHON" -m pip install --upgrade pip setuptools wheel

echo "[2/4] installing the pinned test runner"
"$PYTHON" -m pip install -r requirements.txt

echo "[3/4] installing the morsewire command"
"$PYTHON" -m pip install --no-build-isolation -e .

echo "[4/4] checking that the tool imports"
"$PYTHON" -c 'import morsewire; print("MorseWire", morsewire.VERSION, "ready")'

echo
echo "Setup complete. Start a drill with:  python3 morsewire.py"
echo "                          or:        morsewire"
echo "See --help for every flag, and run 'bash demo.sh' for a scripted run."
