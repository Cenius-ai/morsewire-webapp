# MorseWire design direction

Committed and consumed by `morsewire.py` — this is the source of truth for the
palette, spacing and type. MorseWire is a terminal (CLI) product, so the
"surface" is the terminal and the tokens below are the ones the code actually
paints with; there is no CSS layer and no web font to load.

## Direction

| Token | Value | Where it lives |
| --- | --- | --- |
| Archetype | `cli` | `morsewire.py` (argparse front end, one file) |
| Style family | calm-precise | see the writing rules below |
| Accent (ONE) | `oklch(0.58 0.12 158)` = **`#288f5e`** | `ACCENT_RGB = (40, 143, 94)` |
| Neutral ramp | terminal default foreground + a dim grey `#808a86` | `DIM_RGB = (128, 138, 134)` |
| Warning tone | amber `#c69a3a` (never the only signal) | `WARN_RGB = (198, 154, 58)` |
| Type personality | mono / mono | the terminal's own monospace |
| Density | compact | single-line status rows, no blank-line padding between facts |
| Signature | aligned columns, one accent for primary status, no colour-only signal | `print_banner`, `print_history`, `render_result` |
| Shape language | monospace, no chrome, box-drawing separators (`─`, `═`), same rule width everywhere | `RULE_WIDTH = 62` |

Colour is emitted as 24-bit ANSI (`\x1b[38;2;r;g;bm`) only when stdout is a real
terminal, `NO_COLOR` is unset and `TERM` is not `dumb`; otherwise the text is
byte-identical without escapes. Every coloured line still says the same thing in
words, so a colour-blind or piped run loses nothing.

## Palette (for reference — the CLI is the consumer)

```css
:root {
  --surface: #0b0f0d;              /* terminal dark, the only honest CLI surface */
  --text: #e6eae7;
  --text-dim: #808a86;             /* 5.98:1 on the surface */
  --accent: oklch(0.58 0.12 158);  /* #288f5e, 5.18:1 on the surface */
  --warn: #c69a3a;                 /* 8.08:1 on the surface */
  --rule: #2a332e;
}
```

Contrast: accent 5.18:1, dim 5.98:1, warning 8.08:1 — all above the 4.5:1 floor
against the committed dark surface. The light-terminal case is handled by never
making colour the message: `audio`/`visual`, `sent:`/`copy:` and `^` carets carry
the meaning on their own.

## Layout rules

* Facts are printed as aligned columns (`speed`, `audio`, `history`; `Date`,
  `WPM`, `Accuracy`) rather than as prose, and every rule line is exactly 62
  characters (`RULE_WIDTH`).
* Help is the first thing a curious user reads: `--help` carries one example per
  flag, the history path and the audio-fallback note, hard-wrapped to 80 columns
  (`RawDescriptionHelpFormatter(width=80)`).
* Long Morse renderings wrap on the ` / ` word boundaries at 74 columns plus a
  2-space indent, so nothing ever exceeds 80 columns and no token is split.
* Prompts are one line, and the answer stays on that line: `type what you
  copied: `, `next round [n] or quit [q]? (next at 14 WPM) `.
* Result markers are aligned: the `^` row is offset by `len("sent: ")` so each
  caret sits under the character it flags.

## Type

The user's terminal monospace *is* the type family. No font is loaded, vendored
or fetched — the tool works on a machine with no network and no font cache.
ASCII punctuation does the work; the two box-drawing characters (`─`, `═`) and
the em dash in notices are the only non-ASCII glyphs, and stdout is
reconfigured to UTF-8 with `errors="replace"` so an exotic console degrades
instead of crashing.
