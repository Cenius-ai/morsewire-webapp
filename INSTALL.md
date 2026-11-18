# Installing MorseWire

MorseWire is one Python file. "Installing" it means having a Python interpreter;
everything else is optional.

## Prerequisites

| Requirement | Why | Check |
| --- | --- | --- |
| Python 3.8+ | runs `morsewire.py` | `python3 --version` |
| A terminal, 80 columns | the drill is terminal-only | any terminal |
| *Optional* `afplay` (macOS) / `aplay` or `paplay` (Linux) / PowerShell (Windows) | plays the tones | `command -v aplay` |

There are **no system libraries to install**, no compilers, no database, no
browser and no network access at any point. If no audio player is present the
drill prints one line and sends the round visually instead, so a machine with
no audio is a fully supported configuration.

## 1. Get the files

Unpack the archive (or `git clone`) and change into the project directory —
`morsewire.py` is at the top level:

```bash
cd morsewire
python3 morsewire.py --version
```

That is already the whole product. The remaining steps are optional.

## 2. Install the tooling (optional, one command, then it exits)

```bash
bash install.sh
```

`install.sh` runs as your normal user, uses pip only (never sudo, apt, brew or
system services), and finishes by printing the run command. It performs four
steps:

1. upgrades `pip`, `setuptools` and `wheel`
2. installs the pinned test runner from `requirements.txt` (`pytest`)
3. installs this project in editable mode, which puts a `morsewire` command on
   your PATH
4. imports the module as a self-check

If you would rather not install anything, use `python3 morsewire.py` everywhere
instead of `morsewire`.

## 3. Try it hands-free

```bash
bash demo.sh
```

This runs the real tool against scripted keystrokes (help, the character table,
two short drills, then the history listing) and writes to
`/tmp/morsewire-demo-history.jsonl`, so your own history is untouched.

## 4. Run a drill

```bash
python3 morsewire.py
```

You will be asked for a phrase. Type one, copy it back from the tones (or from
the dots and dashes), and press `n` for the next round or `q` to stop. `--help`
lists every flag.

## 5. Run the tests (optional)

```bash
python3 -m pytest
```

50 tests, no network, no fixtures on disk. They use `MORSEWIRE_HISTORY`-style
temporary directories, so they never touch `~/.morsewire/`.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `No audio player found — this round is visual-only.` | No `afplay`/`aplay`/`paplay`/PowerShell on PATH. Install one, or keep using visual mode, or pass `--no-audio` to skip the probe. |
| `Playback failed — sending visually this round.` | The player exists but could not play the temp WAV. The round continues visually; the WAV is deleted either way. |
| `morsewire: could not write history to …` | `~/.morsewire/` is not writable. Point `MORSEWIRE_HISTORY` at a writable path; the drill keeps running without history. |
| `Please type at least one character.` | The phrase was blank — that is the drill refusing to send nothing. |
| `No supported characters there — see --list-chars.` | Nothing in the phrase is in the A-Z / 0-9 / punctuation table. |
| Colours look wrong | Colour is auto-disabled when stdout is not a terminal or `NO_COLOR` is set. `TERM=dumb` does the same. |

## Uninstall

```bash
python3 -m pip uninstall morsewire     # only if you ran install.sh
rm -rf ~/.morsewire                    # your drill history
```
