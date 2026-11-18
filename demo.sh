#!/usr/bin/env bash
# MorseWire end-to-end demo: non-interactive, no configuration, no network.
# It runs the real tool against scripted keystrokes and writes to a throwaway
# history file so your own ~/.morsewire/history.jsonl is left alone.
set -euo pipefail
cd "$(dirname "$0")"

MORSEWIRE_HISTORY="${TMPDIR:-/tmp}/morsewire-demo-history.jsonl"
export MORSEWIRE_HISTORY
rm -f "$MORSEWIRE_HISTORY"

PYTHON="${PYTHON:-python3}"
rule() { printf '%s\n' "════════════════════════════════════════════════════════════"; }

echo "MorseWire demo — 4 steps, roughly five seconds"
echo

rule
echo "1/4  help — every flag, plus the history path and the audio fallback"
rule
"$PYTHON" morsewire.py --help

echo
rule
echo "2/4  character set — every character the drill can send"
rule
"$PYTHON" morsewire.py --list-chars

echo
rule
echo "3/4  two rounds: a clean copy, then a copy with one slip (marked with ^)"
rule
printf '%s\n' \
  'PARIS THE QUICK BROWN FOX' \
  'paris the quick brown fox' \
  'n' \
  'paris the quick brown fux' \
  'q' \
  | "$PYTHON" morsewire.py --no-audio --start-wpm 12 --ramp 2 --max-wpm 14

echo
rule
echo "4/4  a shorter session at a faster start, then the stored history"
rule
printf '%s\n' \
  'CQ CQ DE N0CALL' \
  'cq cq de n0call' \
  'n' \
  'cq cq de n0call' \
  'q' \
  | "$PYTHON" morsewire.py --no-audio --start-wpm 15 --ramp 3 --max-wpm 21

echo
"$PYTHON" morsewire.py --history

echo
echo "Demo complete — 4 rounds written to $MORSEWIRE_HISTORY"
