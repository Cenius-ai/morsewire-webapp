"""Text handling, scoring, the speed ramp, synthesis and player detection."""

from __future__ import annotations

import io
import stat
import sys
import wave
from pathlib import Path

import pytest

import morsewire


# ---------------------------------------------------------------- text ----
def test_translate_puts_slash_between_words():
    assert morsewire.translate("sos 123") == "... --- ... / .---- ..--- ...--"


def test_translate_drops_unsupported_characters():
    assert morsewire.drill_text("Sos!") == "SOS"
    assert morsewire.unsupported_chars("Sos!") == ["!"]
    assert morsewire.translate("Sos!") == "... --- ..."


def test_unsupported_characters_are_deduplicated_and_ordered():
    assert morsewire.unsupported_chars("a!b!~#") == ["!", "~", "#"]


def test_normalize_case_folds_collapses_and_strips():
    assert morsewire.normalize("  paris   the  Fox \t") == "PARIS THE FOX"


def test_table_covers_letters_digits_and_punctuation():
    assert morsewire.MORSE_TABLE["A"] == ".-"
    assert morsewire.MORSE_TABLE["0"] == "-----"
    assert morsewire.MORSE_TABLE["?"] == "..--.."
    assert "!" not in morsewire.MORSE_TABLE
    assert len(morsewire.MORSE_TABLE) == 51


def test_wrap_tokens_never_splits_a_token_and_respects_width():
    line = morsewire.translate("PARIS THE QUICK BROWN FOX")
    wrapped = morsewire.wrap_tokens(line, 20)
    assert all(len(part) <= 20 for part in wrapped)
    assert " ".join(wrapped) == line


# -------------------------------------------------------------- scoring ----
def test_score_marks_each_mismatched_position():
    score = morsewire.score_copy("PARIS", "PARSI")
    assert score.accuracy == 60
    assert score.mismatch_positions == (3, 4)


def test_score_of_one_wrong_character_is_eighty_percent():
    score = morsewire.score_copy("PARIS", "PARIX")
    assert score.accuracy == 80
    assert score.mismatch_positions == (4,)


def test_score_of_exact_copy_is_perfect():
    score = morsewire.score_copy("PARIS", "PARIS")
    assert score.accuracy == 100
    assert score.mismatch_positions == ()


def test_score_of_blank_copy_marks_every_position():
    score = morsewire.score_copy("PARIS", "")
    assert score.accuracy == 0
    assert score.mismatch_positions == (0, 1, 2, 3, 4)


def test_score_of_empty_sent_text_does_not_divide_by_zero():
    score = morsewire.score_copy("", "anything")
    assert score.accuracy == 0
    assert score.mismatch_positions == ()


def render(record: morsewire.RoundRecord) -> str:
    console = morsewire.Console(stdout=io.StringIO(), stdin=io.StringIO(), stderr=io.StringIO(), color=False)
    morsewire.render_result(record, console)
    return console.stdout.getvalue()


def test_render_result_puts_copy_directly_under_sent_with_carets():
    record = morsewire.build_record(
        index=1,
        phrase="PARIS",
        morse=morsewire.translate("PARIS"),
        copied="parsi",
        wpm=12,
        mode="visual",
        timestamp="2024-05-01T18:04:00+00:00",
    )
    lines = render(record).splitlines()
    sent_index = next(i for i, line in enumerate(lines) if line.startswith("sent: "))
    assert lines[sent_index] == "sent: PARIS"
    assert lines[sent_index + 1] == "copy: PARSI"
    assert sent_index + 1 == lines.index("copy: PARSI")
    marker_line = lines[sent_index + 2]
    # carets sit under the mismatched characters of the sent line: 3 and 4 -> columns 9, 10
    assert [index for index, char in enumerate(marker_line) if char == "^"] == [
        len("sent: ") + 3,
        len("sent: ") + 4,
    ]
    assert "accuracy: 60%  speed: 12 WPM  mode: visual" in lines


def test_render_result_perfect_copy_has_no_carets():
    record = morsewire.build_record(1, "PARIS", morsewire.translate("PARIS"), "paris", 12, "visual", "t")
    text = render(record)
    assert "^" not in text
    assert "accuracy: 100%" in text


# ----------------------------------------------------------- speed ramp ----
def test_ramp_steps_linearly_and_stops_at_the_cap():
    assert morsewire.wpm_for_round(12, 2, 20, 0) == 12
    assert morsewire.wpm_for_round(12, 2, 20, 3) == 18
    assert morsewire.wpm_for_round(12, 2, 20, 4) == 20
    assert morsewire.wpm_for_round(12, 2, 20, 7) == 20


def test_session_state_derives_current_wpm_and_mean():
    state = morsewire.SessionState(start_wpm=12, ramp_step=2, max_wpm=20)
    assert state.current_wpm == 12
    state.rounds = [
        morsewire.build_record(1, "PARIS", "", "PARIS", 12, "visual", "t"),
        morsewire.build_record(2, "PARIS", "", "PARIX", 14, "visual", "t"),
        morsewire.build_record(3, "PARIS", "", "PARRX", 16, "visual", "t"),
    ]
    assert state.rounds_scored == 3
    assert state.current_wpm == 18
    assert state.mean_accuracy == 80


# ------------------------------------------------------------ synthesis ----
def test_wav_is_16_bit_mono_and_matches_paris_timing(tmp_path):
    morse = morsewire.translate("SOS")
    destination = tmp_path / "round.wav"
    written = morsewire.synthesize_wav(morse, 12, destination)
    assert written == destination
    with wave.open(str(destination), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getframerate() == morsewire.SAMPLE_RATE
        frames = handle.getnframes()
    # 27 dot units at 12 WPM: 9 dots, 2 dashes' worth of gaps, 2 word-char gaps.
    expected = 27 * morsewire.unit_seconds(12)
    actual = frames / morsewire.SAMPLE_RATE
    assert abs(actual - expected) / expected < 0.05
    assert abs(morsewire.wav_duration_seconds(morse, 12) - expected) < 1e-9


def test_wav_contains_audible_tone_energy(tmp_path):
    destination = tmp_path / "round.wav"
    morsewire.synthesize_wav(morsewire.translate("E"), 12, destination)
    with wave.open(str(destination), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
    samples = [
        int.from_bytes(frames[index:index + 2], "little", signed=True)
        for index in range(0, len(frames), 2)
    ]
    assert max(samples) > 3000
    assert min(samples) < -3000


def test_empty_morse_writes_no_wav(tmp_path):
    destination = tmp_path / "nothing.wav"
    assert morsewire.synthesize_wav("", 12, destination) is None
    assert not destination.exists()


def test_faster_speed_makes_a_shorter_wav(tmp_path):
    slow = morsewire.synthesize_wav(morsewire.translate("CQ"), 10, tmp_path / "slow.wav")
    fast = morsewire.synthesize_wav(morsewire.translate("CQ"), 20, tmp_path / "fast.wav")
    with wave.open(str(slow), "rb") as handle:
        slow_frames = handle.getnframes()
    with wave.open(str(fast), "rb") as handle:
        fast_frames = handle.getnframes()
    assert fast_frames < slow_frames


# ------------------------------------------------------ player detection ----
def _make_executable(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def test_detect_player_prefers_afplay(monkeypatch, tmp_path, stub_player_detection):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(bin_dir, "aplay")
    _make_executable(bin_dir, "afplay")
    monkeypatch.setenv("PATH", str(bin_dir))
    player = stub_player_detection()
    assert player is not None
    assert player.name == "afplay"


def test_detect_player_falls_back_to_paplay(monkeypatch, tmp_path, stub_player_detection):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _make_executable(bin_dir, "paplay")
    monkeypatch.setenv("PATH", str(bin_dir))
    player = stub_player_detection()
    assert player is not None
    assert player.name == "paplay"


def test_detect_player_returns_none_when_nothing_is_installed(monkeypatch, tmp_path, stub_player_detection):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert stub_player_detection() is None


def test_play_wav_reports_failure_as_playback_error(tmp_path):
    wav = tmp_path / "round.wav"
    morsewire.synthesize_wav(morsewire.translate("PARIS"), 12, wav)
    player = morsewire.Player(name="afplay", command=(str(tmp_path / "missing-player"),))
    with pytest.raises(morsewire.PlaybackError):
        morsewire.play_wav(player, wav)


def test_play_wav_runs_the_player_command(tmp_path):
    wav = tmp_path / "round.wav"
    morsewire.synthesize_wav(morsewire.translate("PARIS"), 12, wav)
    player = morsewire.Player(name="afplay", command=(sys.executable, "-c", "pass"))
    morsewire.play_wav(player, wav)  # exits 0, so no PlaybackError
