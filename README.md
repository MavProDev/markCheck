# markcheck

![tests](https://github.com/MavProDev/markcheck/actions/workflows/ci.yml/badge.svg)

Find characters hiding in text that your screen will not show you.

```bash
pip install markcheck
markcheck essay.md
```

```
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

Exit code `0` means clean, `1` means hidden characters were found. Add
`--strip` to write a cleaned copy.

## What it finds

Six categories of characters that render as nothing, or as an ordinary space,
while occupying real bytes: zero-width characters, invisible format controls,
bidirectional controls, variation selectors, nonstandard whitespace, and the
Unicode Tags block. People
use that gap for text watermarking, for steganographic payloads, and for
Trojan-Source attacks (CVE-2021-42574). The narrow no-break space reported in
ChatGPT output in 2025, U+202F, is in scope here.

markcheck tells you what is present, exactly where, and what it is. It can hand
back a cleaned copy too.

One file. Standard library only. Zero dependencies. No list of AI vendors to
check against, because it does not care who or what wrote the text. It reads
bytes.

## Scope

Three techniques get grouped together as "AI watermarking." Only one of them
puts anything in the bytes, and that is the one markcheck handles.

1. File provenance metadata (C2PA). A signed manifest in the container of an
   image or PDF. Removed by screenshots, format conversion, or re-saving.
   markcheck does not read it; use `c2patool` or `exiftool`.
2. Hidden or lookalike characters. Non-printing code points, or space variants
   that render like a space but carry a different code, inserted into the
   text. markcheck detects these.
3. Statistical / token-distribution watermarks. These bias which ordinary
   words a model selects and add no hidden character, so nothing in the byte
   stream can reveal them. markcheck cannot detect this class, and neither can
   any byte scanner. Rewriting the text in your own words removes it.

A statistical watermark and a hidden-character mark are different mechanisms,
and only the second leaves anything for a byte scanner to find. Where a vendor
is reported to use one or the other, treat the specific claim as something to
verify against that vendor's own documentation rather than against this README:
attribution changes over time, and markcheck deliberately carries no vendor
list. What it reports is a fact about the bytes in front of it.

A CLEAN result means "no hidden characters." It does not mean "not
AI-generated" and it does not mean "unwatermarked."

## Install

Requires Python 3.9 or newer. Nothing else.

```bash
pip install markcheck                                   # from PyPI
pipx install markcheck                                  # isolated CLI install
pip install git+https://github.com/MavProDev/markcheck  # straight from source
```

No install at all: download `markcheck.py` and run it.

```bash
python3 markcheck.py FILE
```

Runs anywhere CPython does: Linux, macOS, Windows, Android (Termux, Pydroid),
and iOS (a-Shell, Pythonista).

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
markcheck FILE --suspicious-only          # drop the likely-legitimate hits
markcheck FILE --min-severity high        # only the reordering/smuggling ones
markcheck FILE --include-default-ignorables  # forensic: every ignorable point
markcheck FILE --strip --force            # overwrite an existing .clean file
markcheck FILE --max-bytes 0         # disable the 100 MB size guard
markcheck FILE --max-hits 0          # disable the hit-count cap
markcheck --list-categories
```

Exit codes: `0` clean, `1` hidden characters found, `2` usage or I/O error.
On POSIX, a closed pipe (`markcheck big.md | head`) terminates with the
conventional `141` rather than reporting success.
This suits a pre-commit hook or CI step:

```bash
git diff --cached --name-only --diff-filter=ACM | grep '\.md$' \
  | xargs -r markcheck || { echo "Hidden characters found."; exit 1; }
```

### Editing files safely

`--strip` never touches the original by default; it writes `FILE.clean.EXT`, and
refuses if that file already exists — pass `--force` to overwrite it.
`--in-place` overwrites the original but first writes a `FILE.bak` backup, and
refuses to run if a `.bak` already exists (so a second run cannot destroy your
one backup). The backup name is claimed with an atomic exclusive create, so two
concurrent runs cannot both decide the backup is free. `--force` deliberately
does *not* override this one: move the `.bak` or pass `--no-backup`. All writes
are atomic: markcheck writes a temp file, fsyncs it, renames it into place, and
fsyncs the directory, so an interrupted run cannot leave a half-written file.

Atomic replacement preserves permission bits. It does **not** preserve
ownership, timestamps, ACLs, or extended attributes; if you rely on those, clean
to a copy rather than in place.

On Windows, the console often uses a locale codec such as cp1252 that cannot
represent most of Unicode. markcheck writes cleaned `--stdout` text as bytes
in the source encoding rather than through that layer, and substitutes an
escape for report text the console cannot render, so a filename or a document
outside the console codec degrades the display instead of ending the run.

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
read, so a UTF-16 document does not silently become a UTF-8 one; the exact
byte order is preserved, so a big-endian file stays big-endian and the
byte-order mark the decoder consumed is restored on the way out. Line endings
are preserved as found, so a CRLF file stays CRLF. A UTF-8 BOM is preserved and
reported (it is itself a zero-width character). With `--in-place`, the `.bak`
backup is a byte-for-byte copy of the original file, not a re-encode, so it is
a faithful image whatever the source encoding. markcheck will not guess a
legacy 8-bit encoding such as Latin-1: a wrong guess would corrupt the bytes it
is meant to inspect, so it reports a clear error and asks you to re-save as
UTF-8.

## Categories

| category | contents | notes |
|----------|----------|-------|
| `zero-width` | ZWSP, ZWJ, ZWNJ, word joiner, invisible math operators, BOM | ZWJ is valid in emoji and Indic scripts; likely-legitimate uses are annotated |
| `invisible-format` | soft hyphen, grapheme joiner, script fillers, interlinear annotation, deprecated format controls | context-dependent |
| `bidi` | LRM/RLM, embeddings, overrides, isolates | valid in RTL text; overrides enable Trojan-Source reordering |
| `variation-selector` | VS1 to VS16, the supplement, Mongolian FVS | normally style glyphs; abusable as payload carriers |
| `tag` | Unicode Tags block (U+E0000 to U+E007F) | invisible; text smuggling and prompt injection; rare in prose |
| `whitespace` | NBSP, NNBSP, en/em/thin/hair spaces, line and paragraph separators, ideographic space | render like a space but differ from U+0020; the class behind the 2025 NNBSP reports |
| `default-ignorable` | every remaining Unicode default-ignorable code point, including reserved ranges | **opt-in**, off by default; enable with `--include-default-ignorables` |

On the narrow no-break space: in 2025 there were widely-circulated reports of
U+202F appearing in output from some ChatGPT models, and discussion of whether
it was a deliberate watermark or an artifact of training. markcheck takes no
position on intent, and does not restate any vendor's explanation as settled
fact. It reports that the character is present, which is a fact about the bytes,
and leaves attribution to you.

### Severity

Every hit is rated, so you can separate a watermark from an emoji:

| severity | what lands here |
|----------|-----------------|
| `info` | annotated, likely-legitimate uses: BOM at file start, emoji ZWJ, presentation selectors, French spacing, digit grouping |
| `low` | ordinary nonstandard whitespace, and the opt-in default-ignorable set |
| `medium` | unexplained zero-width, invisible-format, and variation selectors; bidi direction marks |
| `high` | bidi embeddings, overrides, and isolates (Trojan-Source), and the Unicode Tags block (text smuggling) |

`--suspicious-only` is shorthand for `--min-severity medium`. The filter narrows
*scope*, not just display: the exit code and `--strip` follow it, so
`--suspicious-only --strip` is a conservative cleanup that removes what was
reported and leaves the emoji joiners alone.

```bash
markcheck essay.md --suspicious-only            # skip the benign annotations
markcheck *.md --min-severity high              # CI: only the attack classes
markcheck notes.md --suspicious-only --strip    # clean without breaking emoji
```

### Forensic mode

`--include-default-ignorables` adds a seventh, opt-in category covering every
remaining Unicode `Default_Ignorable_Code_Point`, including reserved ranges. It
is off by default because it is noisy. The range table is frozen at a pinned
Unicode version inside markcheck rather than read from the running Python, so it
also serves as the specification oracle the curated taxonomy is tested against —
that is what catches an omission the Python/JS parity check cannot see.

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

On ordinary prose with sparse hits, peak scan memory measures about **3.4x** the
input size — but that ratio is not a bound. It is dominated by the stored hit
records, so a pathological file that is mostly hidden characters reaches ~140x
with the cap disabled; `--max-hits` (default 200,000), not the input size, is
what bounds the worst case. Throughput is hardware-dependent and was roughly
0.7–2 MB/s on the modest container used for development.

Reproduce both on your own machine rather than taking these numbers on faith:

```bash
python3 tools/benchmark.py --mb 4
```

Exit code `1` means "hidden characters found" (linter semantics: non-zero
signals something to look at), the opposite of `grep`.

## Browser version

`web/index.html` is a single self-contained page: paste text, see what is
hiding in it. It runs entirely in the browser, so no text is uploaded, stored,
or logged. Useful for anyone who does not live in a terminal, including
students, teachers, editors, and hiring teams.

The page is generated from `markcheck.py` by `tools/build_web.py`, never
edited by hand, and `tools/check_parity.py` proves the two implementations
agree across 1530 cases on every hit, position, name, note, severity, and
cleaned output. CI fails if the committed page drifts from the module.

The page ships a restrictive Content-Security-Policy. `connect-src 'none'` is
what technically backs the "nothing is uploaded" claim: the page cannot make a
network request even if it wanted to. One caveat worth stating plainly:
`frame-ancestors` is **ignored** when a policy is delivered in a `<meta>` tag,
so it is not included there. If you host this page and want clickjacking
protection, send it as an HTTP response header:

```
Content-Security-Policy: frame-ancestors 'none'
```

```bash
python3 tools/build_web.py     # regenerate web/index.html
python3 tools/check_parity.py  # prove it matches markcheck.py (needs Node)
```

## Man page and shell completion

Both are generated from the argparse parser by `tools/build_docs.py`, so a new
flag cannot ship with a stale man page. CI regenerates and diffs them.

```bash
man -l docs/markcheck.1                     # read without installing
source completions/markcheck.bash           # bash
cp completions/markcheck.zsh ~/.zfunc/_markcheck   # zsh (with ~/.zfunc in fpath)
```

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
