# Using MorseWire

A session is: pick a phrase once, then copy it back from Morse over and over
while the speed climbs. Every scored round lands in your history file.

## Flags

| Flag | Default | What it does |
| --- | --- | --- |
| `--start-wpm N` | 12 | speed of round 1, 5–60 WPM |
| `--ramp N` | 2 | WPM added after each scored round, 1–20 |
| `--max-wpm N` | 25 | speed cap, must be ≥ `--start-wpm` |
| `--no-audio` | off | never probe or play audio; draw the Morse instead |
| `--history` | — | print stored rounds, then exit 0 |
| `--list-chars` | — | print the supported characters, then exit 0 |
| `--help`, `--version` | — | usage and version, then exit 0 |

Exit codes: `0` success (including quitting mid-drill), `2` bad usage.

## Phrase entry

```
Type a phrase, then copy it back each round. 'quit' exits.
e.g. PARIS THE QUICK BROWN FOX
Phrase to drill: hello!
Skipping unsupported: !
Drilling: HELLO at 12 WPM (ramp +2, cap 25)
```

* blank or whitespace-only input re-asks: `Please type at least one character.`
* over 60 characters re-asks and says how long the phrase was
* a phrase with no supported characters re-asks with a pointer to `--list-chars`
* `quit` (any case) leaves immediately — nothing is written to history

## A round

Audio available:

```
Round 1 — 12 WPM — audio
sending...
type what you copied: paris the quick brown fox
```

No player, or `--no-audio`:

```
Round 2 — 14 WPM — visual
No audio player found — this round is visual-only.
  .--. .- .-. .. ... / - .... . / --.- ..- .. -.-. -.- / -... .-. --- .-- -.
  / ..-. --- -..-
type what you copied:
```

The temporary WAV is deleted whether playback succeeded, failed or fell back;
a failed player prints `Playback failed — sending visually this round.` and the
round continues in visual mode.

## The result

```
sent: PARIS THE QUICK BROWN FOX
copy: PARIS THE QUICK BROWN FUX
                             ^
accuracy: 96%  speed: 12 WPM  mode: audio
```

The copy line sits directly under the sent line, so each `^` marks the exact
character that drifted. A blank copy is still scored: 0%, every position
marked, round still counted. A perfect copy says `clean copy — every position
matched` instead of showing markers.

## After a round

```
next round [n] or quit [q]? (next at 14 WPM)
```

`n` (or `next`) sends the next round at the faster speed, `q` (or `quit`) ends
the session, anything else re-asks with `press n or q`. At the cap the prompt
says `(next at 25 WPM — cap)`.

## Session summary

```
Rounds: 3  Mean accuracy: 84%  Start: 12 WPM  Final: 18 WPM
Full log: morsewire --history  (~/.morsewire/history.jsonl)
```

With no scored rounds it prints `No rounds scored this session.` and still
exits 0.

## History

```
$ python3 morsewire.py --history
MorseWire history — ~/.morsewire/history.jsonl
──────────────────────────────────────
Date              WPM  Accuracy
2024-05-01 18:04    12      100%
2024-05-01 18:09    14       96%
2 round(s)  mean 98%  best 100%
```

Newest last. A corrupt line is skipped with
`morsewire: skipping unreadable history line 2` on stderr and the listing still
exits 0. With no file yet it prints `No history yet — run a drill first.`

## Character set

`--list-chars` prints all 51 supported characters — A-Z, 0-9 and
`. , ? / ( ) : ; = + - _ " $ '` — one per line with its code, grouped into
letters, digits and punctuation.

## Scripted / piped use

Every prompt reads exactly one line from stdin, so a session can be scripted.
`examples/session.txt` is a ready-made one:

```bash
MORSEWIRE_HISTORY=/tmp/drill.jsonl python3 morsewire.py --no-audio < examples/session.txt
```

The phrase, then one line per round's copy, `n`/`q` between rounds. End of input
at any point is a clean exit, not an error.

## Speed ramp

`wpm = min(start_wpm + ramp × rounds_scored, max_wpm)` — one point faster per
scored round, never above the cap, and derived from the round count so a
half-finished round can never advance it twice.
