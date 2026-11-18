"""Shared fixtures: drive the CLI in-process with a scripted stdin."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# The bare `pytest` console script does not add the project root to sys.path,
# so make the single-file tool importable before the fixtures import it.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import morsewire  # noqa: E402  (path is set up immediately above)


@dataclass(frozen=True)
class CliResult:
    code: int
    out: str
    err: str
    history: Path


@pytest.fixture(autouse=True)
def stub_player_detection(monkeypatch):
    """Deterministic default: no player, so rounds go visual.

    Returns the real probe so the player-detection tests can still exercise it.
    """
    original = morsewire.detect_player
    monkeypatch.setattr(morsewire, "detect_player", lambda: None)
    return original


@pytest.fixture
def run_cli(monkeypatch, tmp_path):
    """Run morsewire.main() with scripted stdin and captured streams."""

    def run(stdin_text: str, *argv: str) -> CliResult:
        history = tmp_path / "history.jsonl"
        monkeypatch.setenv("MORSEWIRE_HISTORY", str(history))
        stdout, stderr = io.StringIO(), io.StringIO()
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setattr(sys, "stderr", stderr)
        code = morsewire.main(list(argv))
        return CliResult(code, stdout.getvalue(), stderr.getvalue(), history)

    return run
