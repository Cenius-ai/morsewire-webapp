"""End-to-end CLI behaviour: phrase entry, rounds, ramp, summary and history."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import morsewire

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "morsewire.py"


def cli(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def history_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def dump_history(path: Path) -> list[dict]:
    return [json.loads(line) for line in history_lines(path)]


# ------------------------------------------------------------- the flags ----
def test_help_lists_every_flag_with_defaults_and_exits_zero():
    result = cli("--help")
    assert result.returncode == 0
    for flag in ("--start-wpm", "--ramp", "--max-wpm", "--no-audio", "--history", "--list-chars"):
        assert flag in result.stdout
    assert "default 12" in result.stdout
    assert "~/.morsewire/history.jsonl" in result.stdout
    assert "visual" in result.stdout


def test_unknown_flag_exits_two_without_a_traceback():
    result = cli("--bogus")
    assert result.returncode == 2
    assert "unrecognized arguments: --bogus" in result.stderr
    assert "Traceback" not in result.stderr


def test_max_below_start_is_a_usage_error():
    result = cli("--start-wpm", "20", "--max-wpm", "10")
    assert result.returncode == 2
    assert "--max-wpm (10) must be at least --start-wpm (20)" in result.stderr
    assert "Traceback" not in result.stderr


def test_list_chars_prints_the_table_and_exits_zero():
    result = cli("--list-chars")
    assert result.returncode == 0
    assert "A  .-" in result.stdout
    assert "0  -----" in result.stdout
    assert "?  ..--.." in result.stdout
    assert "Phrase to drill" not in result.stdout


def test_one_shot_flags_never_prompt_and_never_write_history(run_cli):
    listing = run_cli("PARIS\nPARIS\nq\n", "--list-chars")
    assert listing.code == 0
    assert "Phrase to drill" not in listing.out
    assert not listing.history.exists()

    stored = run_cli("PARIS\nPARIS\nq\n", "--history")
    assert stored.code == 0
    assert "No history yet — run a drill first." in stored.out
    assert "Phrase to drill" not in stored.out
    assert not stored.history.exists()


# ------------------------------------------------------- phrase entry ----
def test_blank_phrase_reasks_until_a_real_phrase_arrives(run_cli):
    result = run_cli("\n   \nPARIS\nPARIS\nq\n")
    assert result.code == 0
    assert result.out.count("Please type at least one character.") == 2
    assert "Drilling at 12 WPM (ramp +2, cap 25)" in result.out
    assert "  PARIS" in result.out


def test_phrase_of_only_unsupported_characters_reasks(run_cli):
    result = run_cli("!!!\nPARIS\nPARIS\nq\n")
    assert result.code == 0
    assert "No supported characters there — see --list-chars." in result.out
    assert "Drilling at 12 WPM" in result.out
    assert "  PARIS" in result.out


def test_quit_at_the_phrase_prompt_exits_zero_without_history(run_cli):
    result = run_cli("quit\n")
    assert result.code == 0
    assert not result.history.exists()
    assert "No rounds scored this session." in result.out


def test_start_wpm_flags_are_announced_and_kept(run_cli):
    result = run_cli("PARIS\nPARIS\nq\n", "--start-wpm", "10", "--ramp", "2", "--max-wpm", "20")
    assert result.code == 0
    assert "at 10 WPM (ramp +2, cap 20)" in result.out
    assert "Start: 10 WPM" in result.out


def test_unsupported_characters_are_skipped_with_one_line(run_cli):
    result = run_cli("Hello!\nHELLO\nq\n")
    assert result.code == 0
    assert "Skipping unsupported: !" in result.out
    assert "Drilling at 12 WPM" in result.out
    assert "  HELLO" in result.out


# --------------------------------------------------------------- rounds ----
def test_round_announces_speed_and_mode_before_sending(run_cli):
    result = run_cli("PARIS\nPARIS\nq\n")
    assert "Round 1 — 12 WPM — visual" in result.out
    assert "No audio player found — this round is visual-only." in result.out
    header = result.out.index("Round 1 — 12 WPM — visual")
    notice = result.out.index("No audio player found")
    copy_prompt = result.out.index("type what you copied:")
    assert header < notice < copy_prompt


def test_a_round_reads_exactly_one_line_and_keeps_it_raw(tmp_path):
    config = morsewire.SessionConfig(
        start_wpm=12, ramp_step=2, max_wpm=25, audio_enabled=False,
        phrase="PARIS", history_path=tmp_path / "history.jsonl",
    )
    state = morsewire.SessionState(start_wpm=12, ramp_step=2, max_wpm=25)
    console = morsewire.Console(
        stdin=io.StringIO("paris  \n"), stdout=io.StringIO(), stderr=io.StringIO(), color=False
    )
    record = morsewire.run_round(config, state, console)
    assert record is not None
    assert record.copied == "paris  "
    assert record.normalized_copied == "PARIS"
    assert record.accuracy == 100
    assert console.stdout.getvalue().count("type what you copied:") == 1


def test_audio_round_plays_through_the_player_and_cleans_up(monkeypatch, run_cli):
    monkeypatch.setattr(morsewire, "detect_player", lambda: morsewire.Player("afplay", ("afplay",)))
    seen: dict[str, object] = {}

    def fake_play(player, path):
        seen["exists_during_play"] = path.exists()
        seen["path"] = path

    monkeypatch.setattr(morsewire, "play_wav", fake_play)
    result = run_cli("PARIS\nPARIS\nq\n")
    assert result.code == 0
    assert "Round 1 — 12 WPM — audio" in result.out
    assert "sending..." in result.out
    assert seen["exists_during_play"] is True
    assert not Path(seen["path"]).exists()
    assert dump_history(result.history)[0]["mode"] == "audio"


def test_failed_playback_falls_back_to_visual_and_cleans_up(monkeypatch, run_cli):
    monkeypatch.setattr(morsewire, "detect_player", lambda: morsewire.Player("aplay", ("aplay", "-q")))
    seen: dict[str, object] = {}

    def failing_play(player, path):
        seen["path"] = path
        raise morsewire.PlaybackError("aplay exited with status 1")

    monkeypatch.setattr(morsewire, "play_wav", failing_play)
    result = run_cli("PARIS\nPARIS\nq\n")
    assert result.code == 0
    assert "Playback failed — sending visually this round." in result.out
    assert "  .--. .- .-. .. ..." in result.out
    assert not Path(seen["path"]).exists()
    assert dump_history(result.history)[0]["mode"] == "visual"


def test_no_audio_flag_never_probes_and_stays_visual(monkeypatch, run_cli):
    def explode():
        raise AssertionError("--no-audio must not probe for a player")

    monkeypatch.setattr(morsewire, "detect_player", explode)
    result = run_cli("PARIS\nPARIS\nq\n", "--no-audio")
    assert result.code == 0
    assert "Round 1 — 12 WPM — visual" in result.out
    assert "Audio disabled (--no-audio) — this round is visual-only." in result.out


# ----------------------------------------------------- post-result prompt ----
def test_next_starts_a_new_round_at_the_ramped_speed(run_cli):
    result = run_cli("PARIS\nPARIS\nn\nPARIS\nq\n")
    assert result.code == 0
    assert "next round [n] or quit [q]? (next at 14 WPM)" in result.out
    assert "Round 2 — 14 WPM — visual" in result.out
    assert result.out.count("type what you copied:") == 2


def test_unknown_key_at_the_post_result_prompt_reasks(run_cli):
    result = run_cli("PARIS\nPARIS\nx\nq\n")
    assert result.code == 0
    assert "press n or q" in result.out
    assert "Round 2" not in result.out
    assert "Rounds: 1" in result.out


def test_ramp_reaches_the_cap_and_never_passes_it(run_cli):
    script = "PARIS\nPARIS\n" + "n\nPARIS\n" * 6 + "q\n"
    result = run_cli(script, "--start-wpm", "12", "--ramp", "2", "--max-wpm", "18")
    assert result.code == 0
    assert "Round 3 — 16 WPM — visual" in result.out
    assert "Round 4 — 18 WPM — visual" in result.out
    assert "Round 5 — 18 WPM — visual" in result.out
    assert "20 WPM" not in result.out


# -------------------------------------------------------------- summary ----
def test_summary_reports_rounds_mean_start_and_final(run_cli):
    result = run_cli("PARIS\nPARIS\nn\nPARIX\nn\nPARRX\nq\n")
    assert result.code == 0
    assert "Rounds: 3" in result.out
    assert "Mean accuracy: 80%" in result.out
    assert "Start: 12 WPM" in result.out
    assert "Final: 18 WPM" in result.out
    assert "--history" in result.out


def test_end_to_end_two_round_session_writes_two_history_lines(run_cli):
    result = run_cli("PARIS THE QUICK BROWN FOX\nparis the quick brown fox\nn\nparis the quick brown fox\nq\n")
    assert result.code == 0
    entries = dump_history(result.history)
    assert len(entries) == 2
    for entry in entries:
        assert set(entry) == {"timestamp", "wpm", "accuracy", "mode"}
        assert entry["accuracy"] == 100
        assert entry["mode"] == "visual"
    assert [entry["wpm"] for entry in entries] == [12, 14]


# -------------------------------------------------------------- history ----
def test_history_appends_without_touching_existing_lines(run_cli, tmp_path):
    existing = [
        json.dumps({"timestamp": f"2024-04-0{day}T18:04:00+00:00", "wpm": 10 + day, "accuracy": 90, "mode": "audio"})
        for day in range(1, 6)
    ]
    (tmp_path / "history.jsonl").write_text("\n".join(existing) + "\n", encoding="utf-8")
    result = run_cli("PARIS\nPARIS\nq\n")
    assert result.code == 0
    lines = history_lines(result.history)
    assert len(lines) == 6
    assert lines[:5] == existing
    assert json.loads(lines[5])["accuracy"] == 100


def test_history_listing_prints_date_wpm_and_accuracy(run_cli, tmp_path):
    rows = [
        {"timestamp": "2024-05-01T18:04:00+00:00", "wpm": 14, "accuracy": 92, "mode": "audio"},
        {"timestamp": "2024-05-01T18:09:00+00:00", "wpm": 16, "accuracy": 88, "mode": "visual"},
        {"timestamp": "2024-05-02T07:30:00+00:00", "wpm": 18, "accuracy": 100, "mode": "audio"},
    ]
    (tmp_path / "history.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )
    result = run_cli("", "--history")
    assert result.code == 0
    assert "2024-05-01 18:04" in result.out
    assert "2024-05-02 07:30" in result.out
    assert "14" in result.out and "92%" in result.out
    assert result.out.index("2024-05-01 18:04") < result.out.index("2024-05-02 07:30")
    assert "3 round(s)" in result.out


def test_history_listing_reports_an_empty_file(run_cli, tmp_path):
    (tmp_path / "history.jsonl").write_text("", encoding="utf-8")
    result = run_cli("", "--history")
    assert result.code == 0
    assert "No history yet — run a drill first." in result.out


def test_history_listing_skips_a_corrupt_line_and_keeps_going(run_cli, tmp_path):
    good = json.dumps({"timestamp": "2024-05-01T18:04:00+00:00", "wpm": 14, "accuracy": 92, "mode": "audio"})
    last = json.dumps({"timestamp": "2024-05-01T18:19:00+00:00", "wpm": 18, "accuracy": 100, "mode": "audio"})
    (tmp_path / "history.jsonl").write_text(
        good + "\n" + '{"timestamp": "2024-05-01T18:09:0' + "\n" + last + "\n", encoding="utf-8"
    )
    result = run_cli("", "--history")
    assert result.code == 0
    assert "2024-05-01 18:04" in result.out
    assert "2024-05-01 18:19" in result.out
    assert "skipping unreadable history line 2" in result.err


# ------------------------------------------------------------ resilience ----
def test_end_of_input_mid_session_exits_cleanly(run_cli):
    result = run_cli("PARIS\n")  # EOF while waiting for the copy
    assert result.code == 0
    assert "No rounds scored this session." in result.out
    assert not result.history.exists()


def test_history_write_failure_is_reported_but_the_drill_continues(monkeypatch, run_cli, tmp_path):
    def denied(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "open", denied, raising=False)
    result = run_cli("PARIS\nPARIS\nq\n")
    monkeypatch.undo()
    assert result.code == 0
    assert "accuracy: 100%" in result.out
    assert "could not write history" in result.err
