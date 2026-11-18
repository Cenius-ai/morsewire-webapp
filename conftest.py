"""Make the single-file tool importable no matter how pytest was invoked.

`python3 -m pytest` puts the current directory on sys.path; the bare `pytest`
console script does not. MorseWire is one module at the project root, so the
root is prepended here before any test module is collected.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
