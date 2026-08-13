# Changelog

## 1.5.1
- Fix three Windows failures found by the CI matrix. A console using a locale
  codec such as cp1252 cannot encode most of Unicode, so `--strip --stdout`
  raised UnicodeEncodeError on ordinary non-Latin-1 text, and a filename
  outside the console codec crashed the report. Cleaned text is now written
  as bytes in the source encoding, and stdout/stderr use backslashreplace so
  undisplayable characters degrade instead of aborting the run. The binary
  write falls back to a text write when stdout has no binary layer, as under
  redirect_stdout or in a notebook.
- Tests invoke the CLI with explicit UTF-8 bytes rather than subprocess text
  mode, which encodes using the platform locale and made the suite fail on
  Windows for reasons unrelated to the code under test.

## 1.5.0
- `--strip` now writes the cleaned file in the encoding it read. A UTF-16 or
  UTF-32 document was previously transcoded to UTF-8 without warning; the
  byte-order mark consumed at decode time is now restored on write. The
  `.bak` backup is written in the source encoding too.
- `_decode()` returns (text, encoding) and `read_source()` returns
  (text, label, encoding); `write_text()` takes an encoding argument.
- JSON output includes the detected `encoding` per source.

## 1.4.1
- Fix: `markcheck - --strip` treated the conventional stdin dash as a
  filename and wrote a file named `-.clean` into the working directory.
  A `-` argument now resolves to stdin everywhere.
- Fix: `--strip --in-place` on a symlink replaced the link with a regular
  file and left the real document untouched. It now follows the link.
- Fix: the `.bak` backup inherited the temp file's 0600 mode instead of the
  original file's permissions.
- `--stdout` now errors instead of being silently ignored when passed
  without `--strip` or alongside file arguments.
- Strip status lines say "changed" rather than "removed": whitespace hits are
  normalized in place, so the cleaned text is not always shorter.
- Document the symlink and `--stdout` semantics, and note that OpenAI
  attributes the 2025 U+202F sightings to a training artifact.

## 1.4.0
- New `whitespace` category: NO-BREAK SPACE, NARROW NO-BREAK SPACE, the en/em
  space family, line and paragraph separators, NEL, Ogham space mark, and
  ideographic space. Space lookalikes are the class behind the 2025 reports
  of U+202F in ChatGPT output; markcheck now detects them. Use
  `--exclude whitespace` for typeset or French text.
- `--strip` normalizes whitespace hits (ASCII space, or newline for line and
  paragraph separators) instead of deleting them, so cleaning cannot weld
  `10 km` into `10km`. Zero-width characters are still deleted.
- Annotate NBSP/NNBSP used for French punctuation spacing or digit grouping
  as likely legitimate, matching the existing emoji-ZWJ annotations.
- Track the Mongolian free variation selectors (U+180B..U+180D) in the
  variation-selector category.
- The strip status line now reports the exact count of characters removed or
  normalized (replacements do not change text length).

## 1.3.1
- Fix test-suite portability: the broken-pipe test shelled out to `head`,
  which does not exist on Windows; it now runs only where coreutils do.
- Skip the subprocess CLI tests on platforms that cannot spawn processes
  (iOS Python environments such as a-Shell). The tool itself needs no
  subprocess support and runs there unchanged.
- Wrap the handful of lines that exceeded 79 characters, so the lint-clean
  claim reproduces with stock pyflakes and pycodestyle settings.
- Add the GitHub Actions workflow the README badge points to: unittest plus
  lint across Linux, macOS, and Windows on Python 3.9 to 3.13.

## 1.3.0
- Add `--max-bytes` (default 100 MB): refuse oversized inputs before reading
  them into memory. Pass 0 to disable.
- Add `--max-hits` (default 200,000): cap stored hit records so a file that is
  mostly hidden characters cannot exhaust RAM. The reported total stays exact
  even when the per-location list is capped.
- `scan()` now returns a ScanResult(hits, total, capped) namedtuple.

## 1.2.0
- Annotate VS15/VS16 variation selectors following an emoji base as likely
  legitimate, cutting false-alarm noise on ordinary emoji text.
- `--strip --in-place` now preserves the original file's permission bits
  (a 0600 file stays 0600 instead of widening to 0644).
- Atomic writes use a unique temp file and fsync before rename (durable, no
  fixed-name collision between concurrent runs).
- Accept `-` as an explicit stdin argument; clamp `--show` to non-negative.
- Lint clean under pyflakes and pycodestyle.

## 1.1.0
- Graceful encoding handling: detect UTF-16/UTF-32 by BOM; refuse to guess a
  legacy 8-bit codec instead of crashing on non-UTF-8 input.
- Preserve and report a UTF-8 byte-order mark instead of silently dropping it.
- `--strip --in-place` now writes a `.bak` backup by default and refuses to
  overwrite an existing backup; added `--no-backup`. All writes are atomic.
- Clear errors (exit 2) for directories and unreadable files; no tracebacks.
- Expanded tests: real subprocess CLI coverage, encoding cases, strip-safety,
  and randomized round-trip fuzzers. Added CI across OSes and Python 3.9-3.13.

## 1.0.0
- Initial release: categorized hidden-character scanner with strip, JSON,
  category filters, stdin, and exit codes.
