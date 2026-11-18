#!/usr/bin/env python3
"""MorseWire — a Morse code copy drill for the terminal.

Type a phrase, hear it sent as Morse at the round's speed (or read it as dots
and dashes when the machine cannot play audio), type back what you copied, and
get a marked, scored comparison. The speed ramps after every scored round and
each round is appended to a JSON-Lines history file.

Standard library only. No network access at any point.
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Sequence, TextIO

VERSION = "1.0.0"
PROGRAM = "morsewire"
MAX_PHRASE_LEN = 60

# --------------------------------------------------------------------------
# Committed design tokens (calm-precise / terminal dark / mono).
# The accent is #288f5e; every text colour below clears 4.5:1 on a dark
# terminal background. Colour is never the only signal — the words and the
# glyphs say the same thing on their own.
# --------------------------------------------------------------------------
ACCENT_RGB = (40, 143, 94)      # #288f5e
DIM_RGB = (128, 138, 134)
WARN_RGB = (198, 154, 58)
RULE_WIDTH = 62

# --------------------------------------------------------------------------
# Morse table (ITU). '!' is deliberately absent.
# --------------------------------------------------------------------------
MORSE_TABLE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.", "(": "-.--.",
    ")": "-.--.-", ":": "---...", ";": "-.-.-.", "=": "-...-", "+": ".-.-.",
    "-": "-....-", "_": "..--.-", '"': ".-..-.", "$": "...-..-", "'": ".----.",
}

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
DIGITS = "0123456789"
PUNCTUATION = ".,?/():;=+-_\"$'"

# Timing, in dot units (the PARIS standard).
DOT_UNITS = 1
DASH_UNITS = 3
INTRA_CHARACTER_UNITS = 1
INTER_CHARACTER_UNITS = 3
WORD_GAP_UNITS = 7

SAMPLE_RATE = 8000
TONE_HZ = 700.0
AMPLITUDE = 0.55
FADE_SECONDS = 0.005

VISUAL_ONLY_NOTICE = "No audio player found — this round is visual-only."
AUDIO_DISABLED_NOTICE = "Audio disabled (--no-audio) — this round is visual-only."
PLAYBACK_FAILED_NOTICE = "Playback failed — sending visually this round."


def default_history_path() -> Path:
    """History lives at ~/.morsewire/history.jsonl (override with MORSEWIRE_HISTORY)."""
    override = os.environ.get("MORSEWIRE_HISTORY", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".morsewire" / "history.jsonl"


# --------------------------------------------------------------------------
# Terminal I/O
# --------------------------------------------------------------------------
def color_supported(stream: TextIO) -> bool:
    """True-colour only on a real terminal, and never when NO_COLOR is set."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


class Console:
    """All terminal I/O for one run: prompts, results, diagnostics."""

    def __init__(
        self,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        color: bool | None = None,
    ):
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stderr = stderr if stderr is not None else sys.stderr
        self.color = color_supported(self.stdout) if color is None else color

    def paint(self, text: str, rgb: tuple[int, int, int]) -> str:
        if not self.color:
            return text
        return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\x1b[0m"

    def accent(self, text: str) -> str:
        return self.paint(text, ACCENT_RGB)

    def dim(self, text: str) -> str:
        return self.paint(text, DIM_RGB)

    def warn(self, text: str) -> str:
        return self.paint(text, WARN_RGB)

    def say(self, text: str = "") -> None:
        self.stdout.write(text + "\n")
        self.stdout.flush()

    def note(self, text: str) -> None:
        """Diagnostics belong on stderr so piped stdout stays clean."""
        self.stderr.write(text + "\n")
        self.stderr.flush()

    def ask(self, prompt: str) -> str | None:
        """Write the prompt, read exactly one line. None means end of input."""
        self.stdout.write(prompt)
        self.stdout.flush()
        line = self.stdin.readline()
        if line == "":
            self.say("")
            return None
        return line.rstrip("\r\n")


# --------------------------------------------------------------------------
# Text handling
# --------------------------------------------------------------------------
def normalize(text: str) -> str:
    """Case-fold, collapse internal whitespace, strip."""
    return " ".join(text.upper().split())


def drill_text(phrase: str) -> str:
    """The part of a phrase that can actually be sent (unsupported chars dropped)."""
    words = (
        "".join(character for character in word if character in MORSE_TABLE)
        for word in phrase.upper().split()
    )
    return " ".join(word for word in words if word)


def translate_word(word: str) -> str:
    return " ".join(MORSE_TABLE[character] for character in word if character in MORSE_TABLE)


def translate(phrase: str) -> str:
    """Render a phrase as Morse groups; words are separated by ' / '."""
    groups = [translate_word(word) for word in drill_text(phrase).split(" ")]
    return " / ".join(group for group in groups if group)


def unsupported_chars(phrase: str) -> list[str]:
    """Unsupported characters in first-seen order, de-duplicated."""
    seen: list[str] = []
    for character in phrase.upper():
        if character.isspace() or character in MORSE_TABLE or character in seen:
            continue
        seen.append(character)
    return seen


def wrap_tokens(text: str, width: int) -> list[str]:
    """Wrap a space-separated string on token boundaries, never mid-token."""
    lines: list[str] = []
    current = ""
    for token in text.split(" "):
        candidate = token if not current else f"{current} {token}"
        if len(candidate) > width and current:
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def display_path(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    if home and text.startswith(home):
        return "~" + text[len(home):]
    return text


# --------------------------------------------------------------------------
# Speed ramp
# --------------------------------------------------------------------------
def unit_seconds(wpm: int) -> float:
    """One dot at the given speed (PARIS: 1.2 s per dot at 1 WPM)."""
    return 1.2 / wpm


def wpm_for_round(start_wpm: int, ramp_step: int, max_wpm: int, rounds_scored: int) -> int:
    """Derived, never mutated: the ramp is a pure function of scored rounds."""
    return min(start_wpm + ramp_step * rounds_scored, max_wpm)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Score:
    accuracy: int
    mismatch_positions: tuple[int, ...]


def score_copy(normalized_sent: str, normalized_copied: str) -> Score:
    """Positional character comparison; a short copy marks its missing tail."""
    width = max(len(normalized_sent), 1)
    mismatches = tuple(
        index
        for index in range(len(normalized_sent))
        if index >= len(normalized_copied) or normalized_copied[index] != normalized_sent[index]
    )
    matches = len(normalized_sent) - len(mismatches)
    return Score(accuracy=round(100 * matches / width), mismatch_positions=mismatches)


# --------------------------------------------------------------------------
# Session model
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionConfig:
    start_wpm: int = 12
    ramp_step: int = 2
    max_wpm: int = 25
    audio_enabled: bool = True
    phrase: str = ""
    history_path: Path = field(default_factory=default_history_path)


@dataclass
class RoundRecord:
    index: int
    timestamp: str
    sent_phrase: str
    normalized_sent: str
    morse: str
    copied: str
    normalized_copied: str
    mismatch_positions: tuple[int, ...]
    accuracy: int
    wpm: int
    mode: str

    def history_entry(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "wpm": self.wpm,
            "accuracy": self.accuracy,
            "mode": self.mode,
        }


@dataclass
class SessionState:
    start_wpm: int
    ramp_step: int
    max_wpm: int
    rounds: list[RoundRecord] = field(default_factory=list)

    @property
    def rounds_scored(self) -> int:
        return len(self.rounds)

    @property
    def current_wpm(self) -> int:
        return wpm_for_round(self.start_wpm, self.ramp_step, self.max_wpm, self.rounds_scored)

    @property
    def mean_accuracy(self) -> int:
        if not self.rounds:
            return 0
        return round(sum(record.accuracy for record in self.rounds) / len(self.rounds))


@dataclass(frozen=True)
class Player:
    name: str
    command: tuple[str, ...]


class PlaybackError(RuntimeError):
    """The detected player could not play the round."""


# --------------------------------------------------------------------------
# Audio: synthesis, player detection, playback
# --------------------------------------------------------------------------
def morse_segments(morse: str, wpm: int) -> list[tuple[bool, float]]:
    """Split a Morse string into (is_tone, seconds) segments, including gaps."""
    unit = unit_seconds(wpm)
    segments: list[tuple[bool, float]] = []
    pending_gap = 0.0
    for token in morse.split(" "):
        if not token:
            continue
        if token == "/":
            pending_gap = WORD_GAP_UNITS * unit
            continue
        if pending_gap:
            segments.append((False, pending_gap))
            pending_gap = 0.0
        for position, symbol in enumerate(token):
            if position:
                segments.append((False, INTRA_CHARACTER_UNITS * unit))
            units = DOT_UNITS if symbol == "." else DASH_UNITS
            segments.append((True, units * unit))
        pending_gap = INTER_CHARACTER_UNITS * unit
    return segments


def wav_duration_seconds(morse: str, wpm: int) -> float:
    return sum(seconds for _, seconds in morse_segments(morse, wpm))


def tone_chunk(count: int, cache: dict[int, bytes]) -> bytes:
    """One faded 16-bit sine tone, memoised per sample count for the round."""
    import struct

    cached = cache.get(count)
    if cached is not None:
        return cached
    fade = min(max(1, int(FADE_SECONDS * SAMPLE_RATE)), max(count // 2, 1))
    step = 2.0 * math.pi * TONE_HZ / SAMPLE_RATE
    values = []
    for index in range(count):
        envelope = 1.0
        if index < fade:
            envelope = index / fade
        elif count - index <= fade:
            envelope = (count - index) / fade
        values.append(int(32767 * AMPLITUDE * envelope * math.sin(step * index)))
    chunk = struct.pack(f"<{count}h", *values)
    cache[count] = chunk
    return chunk


def synthesize_wav(morse: str, wpm: int, destination: Path) -> Path | None:
    """Write a 16-bit mono sine WAV. Returns None (writing nothing) for empty Morse."""
    if not morse.strip():
        return None
    import wave

    tone_cache: dict[int, bytes] = {}
    chunks: list[bytes] = []
    for is_tone, seconds in morse_segments(morse, wpm):
        count = int(round(seconds * SAMPLE_RATE))
        if count <= 0:
            continue
        chunks.append(tone_chunk(count, tone_cache) if is_tone else b"\x00\x00" * count)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(b"".join(chunks))
    return destination


def detect_player() -> Player | None:
    """Fixed probe order: afplay, aplay, paplay, then PowerShell SoundPlayer."""
    import shutil

    for name, command in (
        ("afplay", ("afplay",)),
        ("aplay", ("aplay", "-q")),
        ("paplay", ("paplay",)),
    ):
        if shutil.which(name):
            return Player(name=name, command=command)
    for executable in ("powershell", "pwsh"):
        if shutil.which(executable):
            return Player(
                name="powershell",
                command=(executable, "-NoProfile", "-NonInteractive", "-Command"),
            )
    return None


def play_wav(player: Player, path: Path) -> None:
    """Play a WAV through the detected player. Raises PlaybackError on failure."""
    import subprocess

    if player.name == "powershell":
        script = f"(New-Object Media.SoundPlayer '{path}').PlaySync();"
        command = [*player.command, script]
    else:
        command = [*player.command, str(path)]
    try:
        subprocess.run(
            command,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=300,
        )
    except subprocess.CalledProcessError as error:
        raise PlaybackError(f"{player.name} exited with status {error.returncode}") from error
    except (OSError, subprocess.SubprocessError) as error:
        raise PlaybackError(f"{player.name} could not run: {error}") from error


def choose_mode(config: SessionConfig) -> tuple[str, Player | None]:
    """Decide the round mode before the header prints, so the header is honest."""
    if not config.audio_enabled:
        return "visual", None
    player = detect_player()
    if player is None:
        return "visual", None
    return "audio", player


def render_morse(morse: str, console: Console) -> None:
    for line in wrap_tokens(morse, 74):
        console.say("  " + console.accent(line))


def deliver_morse(
    config: SessionConfig,
    morse: str,
    wpm: int,
    planned_mode: str,
    player: Player | None,
    console: Console,
) -> str:
    """Send the round. Returns the mode it actually ran in ('audio' | 'visual')."""
    if planned_mode == "audio" and player is not None:
        mode = _play_round(morse, wpm, player, console)
        if mode == "audio":
            return "audio"
        render_morse(morse, console)
        return "visual"
    if config.audio_enabled:
        console.say(console.warn(VISUAL_ONLY_NOTICE))
    else:
        console.say(console.dim(AUDIO_DISABLED_NOTICE))
    render_morse(morse, console)
    return "visual"


def _play_round(morse: str, wpm: int, player: Player, console: Console) -> str:
    import tempfile

    handle, temporary_name = tempfile.mkstemp(prefix="morsewire-", suffix=".wav")
    os.close(handle)
    temporary_path = Path(temporary_name)
    try:
        if synthesize_wav(morse, wpm, temporary_path) is None:
            console.say(console.warn(VISUAL_ONLY_NOTICE))
            return "visual"
        console.say(console.dim("sending..."))
        try:
            play_wav(player, temporary_path)
        except PlaybackError as error:
            console.note(f"{PROGRAM}: playback failed: {error}")
            console.say(console.warn(PLAYBACK_FAILED_NOTICE))
            return "visual"
        return "audio"
    finally:
        temporary_path.unlink(missing_ok=True)


# --------------------------------------------------------------------------
# Round rendering
# --------------------------------------------------------------------------
def render_result(record: RoundRecord, console: Console) -> None:
    sent = record.normalized_sent[:MAX_PHRASE_LEN]
    copied = record.normalized_copied[:MAX_PHRASE_LEN]
    markers = [" "] * len(sent)
    for position in record.mismatch_positions:
        if position < len(markers):
            markers[position] = "^"
    console.say("")
    console.say("sent: " + sent)
    console.say("copy: " + copied)
    if any(marker == "^" for marker in markers):
        console.say(" " * len("sent: ") + console.warn("".join(markers).rstrip()))
    if len(record.normalized_copied) > MAX_PHRASE_LEN:
        console.say(console.dim(f"(copy trimmed to {MAX_PHRASE_LEN} characters for display)"))
    summary = f"accuracy: {record.accuracy}%  speed: {record.wpm} WPM  mode: {record.mode}"
    console.say(console.accent(summary) if record.accuracy == 100 else summary)
    if record.accuracy == 100:
        console.say(console.accent("clean copy — every position matched"))


def build_record(
    index: int,
    phrase: str,
    morse: str,
    copied: str,
    wpm: int,
    mode: str,
    timestamp: str,
) -> RoundRecord:
    normalized_sent = normalize(drill_text(phrase))
    normalized_copied = normalize(copied)
    score = score_copy(normalized_sent, normalized_copied)
    return RoundRecord(
        index=index,
        timestamp=timestamp,
        sent_phrase=phrase,
        normalized_sent=normalized_sent,
        morse=morse,
        copied=copied,
        normalized_copied=normalized_copied,
        mismatch_positions=score.mismatch_positions,
        accuracy=score.accuracy,
        wpm=wpm,
        mode=mode,
    )


# --------------------------------------------------------------------------
# One round
# --------------------------------------------------------------------------
def run_round(config: SessionConfig, state: SessionState, console: Console) -> RoundRecord | None:
    """Announce, send, read exactly one line, score and render. None = aborted."""
    wpm = state.current_wpm
    index = state.rounds_scored + 1
    mode, player = choose_mode(config)
    console.say("")
    console.say(console.accent(f"Round {index} — {wpm} WPM — {mode}"))

    sent = drill_text(config.phrase)
    if not sent:
        console.say(console.warn("Nothing to send — the phrase has no supported characters."))
        return None
    morse = translate(sent)

    actual_mode = deliver_morse(config, morse, wpm, mode, player, console)
    copied = console.ask("type what you copied: ")
    if copied is None:
        return None

    record = build_record(
        index=index,
        phrase=config.phrase,
        morse=morse,
        copied=copied,
        wpm=wpm,
        mode=actual_mode,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    render_result(record, console)
    return record


def ask_next_round(state: SessionState, config: SessionConfig, console: Console) -> bool:
    """True = another round, False = quit. Unknown keys re-ask."""
    next_wpm = state.current_wpm
    suffix = " — cap" if next_wpm >= config.max_wpm else ""
    prompt = f"next round [n] or quit [q]? (next at {next_wpm} WPM{suffix}) "
    while True:
        answer = console.ask(prompt)
        if answer is None:
            return False
        choice = answer.strip().lower()
        if choice in ("n", "next"):
            return True
        if choice in ("q", "quit"):
            return False
        console.say(console.dim("press n or q"))


# --------------------------------------------------------------------------
# Phrase entry
# --------------------------------------------------------------------------
def prompt_phrase(console: Console) -> str | None:
    """Ask until a drillable phrase arrives. None means the user typed 'quit'."""
    console.say(console.dim("Type a phrase, then copy it back each round. 'quit' exits."))
    console.say(console.dim("e.g. PARIS THE QUICK BROWN FOX"))
    while True:
        answer = console.ask("Phrase to drill: ")
        if answer is None:
            return None
        phrase = answer.strip()
        if phrase.lower() == "quit":
            return None
        if not phrase:
            console.say(console.dim("Please type at least one character."))
            continue
        if len(phrase) > MAX_PHRASE_LEN:
            console.say(
                console.dim(
                    f"That phrase is {len(phrase)} characters — keep it to {MAX_PHRASE_LEN} or fewer."
                )
            )
            continue
        if not drill_text(phrase):
            console.say(console.dim("No supported characters there — see --list-chars."))
            continue
        return phrase


def print_banner(config: SessionConfig, console: Console) -> None:
    rule = console.dim("─" * RULE_WIDTH)
    mode_hint = "visual only (--no-audio)" if not config.audio_enabled else "system player when available"
    console.say(console.accent("MorseWire") + " — Morse copy drill")
    console.say(rule)
    console.say(f"speed    {config.start_wpm} WPM, ramp +{config.ramp_step}, cap {config.max_wpm} WPM")
    console.say(f"audio    {mode_hint}")
    console.say(f"history  {display_path(config.history_path)}")
    console.say(rule)


def print_summary(state: SessionState, config: SessionConfig, console: Console) -> None:
    console.say("")
    if not state.rounds:
        console.say("No rounds scored this session.")
        console.say(console.dim(f"Full log: {PROGRAM} --history  ({display_path(config.history_path)})"))
        return
    console.say(
        f"Rounds: {state.rounds_scored}  Mean accuracy: {state.mean_accuracy}%  "
        f"Start: {state.start_wpm} WPM  Final: {state.current_wpm} WPM"
    )
    console.say(console.dim(f"Full log: {PROGRAM} --history  ({display_path(config.history_path)})"))


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------
def append_history(path: Path, record: RoundRecord, console: Console) -> None:
    """Append exactly one JSON line; existing lines are never rewritten."""
    import json  # kept local so --help/--list-chars stay inside the cold-start budget

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.history_entry(), ensure_ascii=False) + "\n")
    except OSError as error:
        console.note(f"{PROGRAM}: could not write history to {path}: {error.strerror or error}")


def read_history_rows(path: Path, console: Console) -> list[tuple[datetime, int, int]]:
    """Parse the JSON-Lines history, reporting and skipping unreadable lines."""
    import json  # kept local so --help/--list-chars stay inside the cold-start budget

    rows: list[tuple[datetime, int, int]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        console.note(f"{PROGRAM}: could not read history at {path}: {error.strerror or error}")
        return rows
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
            timestamp = datetime.fromisoformat(str(data["timestamp"]))
            wpm = int(data["wpm"])
            accuracy = int(data["accuracy"])
        except (ValueError, KeyError, TypeError):
            console.note(f"{PROGRAM}: skipping unreadable history line {line_number}")
            continue
        rows.append((timestamp, wpm, accuracy))
    return rows


def print_history(path: Path, console: Console) -> int:
    """--history: one aligned row per stored round, newest last."""
    if not path.exists():
        console.say("No history yet — run a drill first.")
        return 0
    rows = read_history_rows(path, console)
    if not rows:
        console.say("No history yet — run a drill first.")
        return 0
    console.say(console.accent("MorseWire history") + " — " + display_path(path))
    console.say(console.dim("─" * 38))
    console.say(f"{'Date':<16}  {'WPM':>3}  {'Accuracy':>8}")
    for timestamp, wpm, accuracy in rows:
        console.say(f"{timestamp.strftime('%Y-%m-%d %H:%M'):<16}  {wpm:>3}  {accuracy:>7}%")
    mean = round(sum(row[2] for row in rows) / len(rows))
    best = max(row[2] for row in rows)
    console.say(console.dim(f"{len(rows)} round(s)  mean {mean}%  best {best}%"))
    return 0


# --------------------------------------------------------------------------
# Character set listing
# --------------------------------------------------------------------------
def print_chars(console: Console) -> int:
    """--list-chars: the whole table, grouped letters / digits / punctuation."""
    console.say(console.accent("MorseWire character set") + f" — {len(MORSE_TABLE)} characters")
    for label, characters in (
        ("Letters", LETTERS),
        ("Digits", DIGITS),
        ("Punctuation", PUNCTUATION),
    ):
        console.say("")
        console.say(console.dim(label))
        for character in characters:
            console.say(f"  {character}  {MORSE_TABLE[character]}")
    console.say("")
    console.say(console.dim("Anything else is skipped with a one-line warning."))
    return 0


# --------------------------------------------------------------------------
# Session loop
# --------------------------------------------------------------------------
def run_session(config: SessionConfig, console: Console) -> int:
    state = SessionState(
        start_wpm=config.start_wpm,
        ramp_step=config.ramp_step,
        max_wpm=config.max_wpm,
    )
    print_banner(config, console)
    phrase = prompt_phrase(console)
    if phrase is None:
        print_summary(state, config, console)
        return 0

    skipped = unsupported_chars(phrase)
    if skipped:
        console.say(console.warn("Skipping unsupported: " + " ".join(skipped)))
    config = replace(config, phrase=phrase)
    console.say(
        f"Drilling at {config.start_wpm} WPM "
        f"(ramp +{config.ramp_step}, cap {config.max_wpm})"
    )
    for line in wrap_tokens(drill_text(phrase), 74):
        console.say("  " + line)

    try:
        while True:
            record = run_round(config, state, console)
            if record is None:
                break
            state.rounds.append(record)
            append_history(config.history_path, record, console)
            if not ask_next_round(state, config, console):
                break
    except KeyboardInterrupt:
        console.say("")
        console.say(console.dim("Interrupted."))
    print_summary(state, config, console)
    return 0


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def wpm_value(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number of WPM, got {text!r}")
    if not 5 <= value <= 60:
        raise argparse.ArgumentTypeError("WPM must be between 5 and 60")
    return value


def ramp_value(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a whole number, got {text!r}")
    if not 1 <= value <= 20:
        raise argparse.ArgumentTypeError("the ramp step must be between 1 and 20 WPM")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Morse code copy drill: type a phrase, copy it back from the tones,\n"
            "and get a scored comparison. The speed ramps after every scored\n"
            "round and each round is appended to a history file."
        ),
        epilog=(
            "examples:\n"
            "  python3 morsewire.py                  # default: 12 WPM, ramp +2, cap 25\n"
            "  python3 morsewire.py --start-wpm 15   # start the session at 15 WPM\n"
            "  python3 morsewire.py --ramp 1         # gentler ramp (+1 WPM a round)\n"
            "  python3 morsewire.py --max-wpm 30     # raise the speed cap to 30 WPM\n"
            "  python3 morsewire.py --no-audio       # visual-only, no player probing\n"
            "  python3 morsewire.py --list-chars     # supported characters, then exit\n"
            "  python3 morsewire.py --history        # stored rounds, then exit\n"
            "\n"
            "history: ~/.morsewire/history.jsonl (one JSON line per scored round;\n"
            "         override the location with MORSEWIRE_HISTORY)\n"
            "audio:   falls back to a visual drill, with a one-line notice, when no\n"
            "         system player (afplay, aplay, paplay, PowerShell) is available.\n"
        ),
        formatter_class=lambda prog: argparse.RawDescriptionHelpFormatter(
            prog, width=80, max_help_position=28
        ),
    )
    parser.add_argument("--start-wpm", type=wpm_value, default=12, metavar="N",
                        help="starting speed in words per minute (5-60, default 12)")
    parser.add_argument("--ramp", type=ramp_value, default=2, metavar="N",
                        help="WPM added after every scored round (1-20, default 2)")
    parser.add_argument("--max-wpm", type=wpm_value, default=25, metavar="N",
                        help="speed cap in words per minute (5-60, default 25)")
    parser.add_argument("--no-audio", action="store_true",
                        help="never probe or play audio; draw the Morse instead")
    parser.add_argument("--history", action="store_true",
                        help="print stored rounds (date, WPM, accuracy) and exit")
    parser.add_argument("--list-chars", action="store_true",
                        help="print the supported character set and exit")
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {VERSION}")
    return parser


def configure_streams() -> None:
    """Best-effort UTF-8 so the em dashes and box drawing never crash a console."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            continue


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: a closed downstream pipe (`| head`) is a normal stop, not a crash."""
    try:
        return _main(argv)
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, sys.stdout.fileno())
        finally:
            os.close(devnull)
        return 0


def _main(argv: Sequence[str] | None = None) -> int:
    configure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_wpm < args.start_wpm:
        parser.error(f"--max-wpm ({args.max_wpm}) must be at least --start-wpm ({args.start_wpm})")
    console = Console()
    if args.list_chars:
        return print_chars(console)
    if args.history:
        return print_history(default_history_path(), console)

    config = SessionConfig(
        start_wpm=args.start_wpm,
        ramp_step=args.ramp,
        max_wpm=args.max_wpm,
        audio_enabled=not args.no_audio,
        history_path=default_history_path(),
    )
    try:
        return run_session(config, console)
    except KeyboardInterrupt:
        console.say("")
        console.say(console.dim("Interrupted."))
        return 130


if __name__ == "__main__":
    sys.exit(main())
