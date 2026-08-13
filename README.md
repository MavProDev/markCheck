# markcheck

![tests](https://github.com/MavProDev/markcheck/actions/workflows/ci.yml/badge.svg)

Scan text for hidden and invisible Unicode characters: zero-width characters,
bidirectional controls, variation selectors, nonstandard whitespace, and the
Unicode Tags block. These render as nothing (or as an ordinary-looking space)
but occupy distinct bytes, and are used for text watermarking, steganographic
payloads, and Trojan-Source attacks (CVE-2021-42574). The narrow no-break
space (U+202F) reported in ChatGPT output in 2025 is in scope. markcheck
reports what is present, where, and what it is, and can write a cleaned copy.

Single file, standard library only, no dependencies. Source-agnostic: there is
no allow/deny list tied to any vendor or model.

```
$ markcheck essay.md
Source: essay.md
Characters: 8214
Hidden-character hits: 3
  By category: zero-width=2, bidi=1
  By character:
    U+200B  ZERO WIDTH SPACE                   x2
    U+202E  RIGHT-TO-LEFT OVERRIDE             x1
  Locations (up to 20):
    line   14 col   62  U+200B ZERO WIDTH SPACE
    line   14 col   88  U+200B ZERO WIDTH SPACE
    line   31 col    5  U+202E RIGHT-TO-LEFT OVERRIDE
```

## Scope

Three techniques are commonly grouped as "AI watermarking." Only one puts
anything in the bytes, and that is the one markcheck handles.

1. File provenance metadata (C2PA). A signed manifest in the container of an
   image or PDF. Removed by screenshots, format conversion, or re-saving.
   markcheck does not read it; use `c2patool` or `exiftool`.
2. Hidden or lookalike characters. Non-printing code points, or space
   variants that render like a space but carry a different code, inserted
   into the text. markcheck detects these.
3. Statistical / token-distribution watermarks. These bias which ordinary
   words a model selects and add no hidden character, so nothing in the byte
   stream can reveal them. markcheck cannot detect this class, and neither can
   any byte scanner. Rewriting the text in your own words removes it.

A CLEAN result means "no hidden characters," not "not AI-generated" and not
"unwatermarked."

## Install

Requires Python 3.9 or newer. No dependencies. Runs anywhere CPython does:
Linux, macOS, Windows, Android (Termux, Pydroid), and iOS (a-Shell,
Pythonista).

```bash
python3 markcheck.py FILE        # run directly
pip install .                    # or install; provides a `markcheck` command
```

## Usage

```bash
markcheck FILE [FILE ...]
cat FILE | markcheck
markcheck FILE --strip                    # write FILE.clean.EXT with hits removed
markcheck FILE --strip --in-place         # overwrite original (keeps FILE.bak)
markcheck FILE --strip --in-place --no-backup
cat FILE | markcheck --strip --stdout     # clean a stream to stdout
markcheck FILE --json                     # machine-readable output
markcheck FILE --only zero-width,bidi     # restrict to categories
markcheck FILE --exclude whitespace       # e.g. for typeset or French text
markcheck FILE --max-bytes 0         # disable the 100 MB size guard
markcheck FILE --max-hits 0          # disable the hit-count cap
markcheck --list-categories
```

Exit codes: `0` clean, `1` hidden characters found, `2` usage or I/O error.
This suits a pre-commit hook or CI step:

```bash
git diff --cached --name-only --diff-filter=ACM | grep '\.md$' \
  | xargs -r markcheck || { echo "Hidden characters found."; exit 1; }
```

### Editing files safely

`--strip` never touches the original by default; it writes `FILE.clean.EXT`.
`--in-place` overwrites the original but first writes a `FILE.bak` backup, and
refuses to run if a `.bak` already exists (so a second run cannot destroy your
one backup). Pass `--no-backup` to opt out. All writes are atomic: markcheck
writes a temp file and renames it into place, so an interrupted run cannot
leave a half-written file.

`--in-place` follows a symlink to the real file rather than replacing the
link with a regular file. `--stdout` applies to stdin only; for files, use
`--strip` for a clean copy or `--strip --in-place`.

Stripping is normalization-safe for whitespace: removing a NO-BREAK SPACE
outright would weld `10 km` into `10km`, so whitespace-category hits are
replaced with an ASCII space (line and paragraph separators with a newline)
while zero-width and format characters, which occupy no width, are deleted.

## Encoding

markcheck reads UTF-8 by default and auto-detects UTF-16 and UTF-32 from a
byte-order mark. `--strip` writes the cleaned file back in the encoding it
read, so a UTF-16 document does not silently become a UTF-8 one; the
byte-order mark the decoder consumed is restored on the way out. Line endings
are preserved as found, so a CRLF file stays CRLF. A UTF-8 BOM is preserved and reported (it is itself a
zero-width character). markcheck will not guess a legacy 8-bit encoding such as
Latin-1: a wrong guess would corrupt the bytes it is meant to inspect, so it
reports a clear error and asks you to re-save as UTF-8.

## Categories

| category | contents | notes |
|----------|----------|-------|
| `zero-width` | ZWSP, ZWJ, ZWNJ, word joiner, invisible math operators, BOM | ZWJ is valid in emoji and Indic scripts; likely-legitimate uses are annotated |
| `invisible-format` | soft hyphen, grapheme joiner, script fillers, interlinear annotation, deprecated format controls | context-dependent |
| `bidi` | LRM/RLM, embeddings, overrides, isolates | valid in RTL text; overrides enable Trojan-Source reordering |
| `variation-selector` | VS1 to VS16, the supplement, Mongolian FVS | normally style glyphs; abusable as payload carriers |
| `tag` | Unicode Tags block (U+E0000 to U+E007F) | invisible; text smuggling and prompt injection; rare in prose |
| `whitespace` | NBSP, NNBSP, en/em/thin/hair spaces, line and paragraph separators, ideographic space | render like a space but differ from U+0020; the class behind the 2025 NNBSP reports |

On the narrow no-break space: in 2025 researchers reported U+202F appearing
in output from some ChatGPT models, and OpenAI attributed it to a training
artifact rather than a deliberate watermark. markcheck takes no position on
intent. It reports that the character is present, which is a fact about the
bytes, and leaves attribution to you.

markcheck reports every hit but annotates the common false positives: a
byte-order mark at the start of a file, a ZERO WIDTH JOINER between two emoji,
and NBSP/NNBSP used for French punctuation spacing or digit grouping.
Nonstandard whitespace is genuinely common in word-processor and
professionally typeset text; that is exactly why it works as a fingerprint,
and why markcheck reports it with context instead of deciding for you. Use
`--exclude whitespace` when scanning such text, and `--exclude bidi` for
Arabic or Hebrew.

## Limitations

- Cannot detect statistical / token watermarks; they leave no bytes.
- Cannot read C2PA metadata in binary containers.
- Detection is not attribution: a hidden character shows presence, not origin.

### Deliberately out of scope

markcheck finds characters that are *invisible or space-lookalike*. It does
not flag characters that are *visible but deceptive*, which is a separate
problem with separate tooling:

- **Homoglyphs / confusables** (a Cyrillic lookalike letter standing in for a Latin "a").
  These are visible and legitimate in their own scripts; detecting abuse needs
  mixed-script and confusable analysis (Unicode UTS-39), not a hidden-char scan.
- **Unicode normalization.** markcheck inspects the bytes as given; it does not
  NFC/NFD-normalize, so it will not collapse or compare equivalent sequences.

It reads each file fully into memory. Two caps keep that safe by default:
`--max-bytes` (default 100 MB) refuses oversized inputs before reading them,
and `--max-hits` (default 200,000) caps the number of stored hit records so a
pathological file that is mostly hidden characters cannot exhaust RAM. When the
hit list is capped, the reported total is still exact; only the per-location
list and summaries are limited. Pass `0` to either flag to disable it.

Measured cost on ordinary text is roughly 3x the file size in memory and about
0.2s per MB. Exit code `1` means "hidden characters found" (linter semantics:
non-zero signals something to look at), the opposite of `grep`.

## Tests

```bash
python3 -m unittest -v
```

Covers the pure functions, the CLI through real subprocess invocation,
encoding edge cases, `--strip` safety, and randomized round-trip fuzzers. CI
runs the suite on Linux, macOS, and Windows across Python 3.9 to 3.13. On
iOS, where the OS forbids spawning processes, the subprocess tests skip and
the rest of the suite runs.

## License

MIT. See [LICENSE](LICENSE).
