# Changelog

## 2.2.1
No behaviour changes. Two claims this project makes about itself were resting
on my word rather than on a check, so they are now checked.

### Verification
- **The frozen Unicode table is verified against the property's own
  definition.** `DEFAULT_IGNORABLE` was transcribed from
  DerivedCoreProperties.txt, and a transcription is exactly the kind of thing
  that is quietly wrong. A test now rebuilds the set from the derivation UAX #44
  publishes — Other_Default_Ignorable_Code_Point + Cf + Variation_Selector,
  minus White_Space, the interlinear annotation characters, the Egyptian
  hieroglyph format controls, and the prepended concatenation marks — and
  asserts the two agree exactly. `Cf` and `White_Space` come from the
  interpreter, so the two sides share no data and agreement means something.
  They match on all 4,174 code points. A future Unicode release that adds a
  format character none of the exclusions cover will now fail the test rather
  than drift silently.
- **The deployment function is tested in every storage state.** `web/api/index.js`
  only ever runs on Vercel, which made it the one piece nobody would see fail
  until it was live. `tools/check_api.js` now drives it directly: the count is
  injected when storage answers, and the page is still served with the counter
  hidden when storage is unconfigured, returns an error, throws, or answers with
  something that is not a number. A source check asserts the function never
  reads `req.headers`, `x-forwarded-for`, `remoteAddress`, or the user agent, so
  the promise that no visitor metadata is collected is enforced rather than
  merely documented. Wired into CI.

Still unproven, and stated plainly: Vercel's `/` → `/api/index` rewrite cannot
be exercised without a deployment. The function's behaviour is covered; the
platform wiring is not.

## 2.2.0
Adds an "About this tool" page. No scanner changes: the engine, the CLI, and
the parity suite are untouched.

### Added
- **`web/about.html`** — what markcheck is, what happens to your text, what it
  deliberately cannot do, how to use it, how to read the severity ratings, the
  command line tool, and why you can verify the privacy claim rather than take
  it on trust. Generated like the other pages and gated in CI.
- The privacy section is the point of it: it explains that `connect-src 'none'`
  is *enforced by the browser rather than promised by us*, is explicit that the
  visit counter stores a single integer and no IP address, user agent, or
  per-visitor record, and invites the reader to confirm all of it in their own
  network tab or with the wifi off.
- A contents strip that jumps to each section, and cross-links between the
  three pages.

### Changed
- The design tokens, glass, header, hero, footer, and the reduced-motion,
  reduced-transparency, and increased-contrast rules now live in
  `tools/shared.css` and are substituted into the generated pages at build
  time, instead of being copy-pasted per template. The scanner page keeps its
  own stylesheet deliberately: it has diverged for real reasons (severity
  colours, glass tuned around an 8,000-node preview) and the parity harness
  slices the engine out of that file by string offsets, so deduplicating it
  would risk the shipped scanner to save repetition in a generated file.

### Fixed
- The contents strip on the about page is a `<nav>`, so it inherited the sticky
  glass header treatment and rendered as a grey slab across the page. The
  header rules are now scoped to `body > nav`. Caught by looking at a
  screenshot; the automated checks passed straight over it.

### Tests
- A leak guard across all three generated pages: no email address, no outbound
  URL other than the public repository, and no commit trailer. It matches on
  what a leak actually looks like rather than on substrings, since CSS is full
  of `@media` and every page carries an `http-equiv` meta tag.
- A check that no page ships an unsubstituted template marker.
- The browser pass now covers the about page in both themes and on a phone,
  asserting every contents link resolves to a real section.

## 2.1.0
A visual and functional overhaul of the browser build. The scanner engine is
untouched — the Python/JavaScript parity suite passes unchanged — so this is
presentation, ergonomics, and deployment only.

### Added
- **Redesigned interface.** A translucent, layered treatment with an adaptive
  light and dark palette, a manual theme switch that overrides the system
  setting, and restrained motion: spring-eased controls, a staggered result
  reveal, and a counting verdict figure.
- **Severity, surfaced.** The 2.0.0 severity model is now visible in the
  browser: colour-coded chips, a proportional severity bar, and a **Suspicious
  only** switch that applies the same `--min-severity medium` scope as the CLI,
  so a conservative clean will not break emoji sequences.
- **Drag and drop a text file** onto the page, or pick one. Read locally with
  FileReader; the file never leaves the machine.
- **Command palette** on `⌘K` / `Ctrl-K`, plus `⌘↵` to scan and `Esc` to clear.
- **Before / after view** comparing the original with the cleaned text.
- **Export report** writes the findings to JSON locally, via a Blob. No upload.
- **Patch notes page** at `web/changelog.html`, generated from `CHANGELOG.md` by
  `tools/build_web.py` and gated in CI like the rest of the web build. It is
  generated from that file alone, never from git history, whose commit trailers
  carry addresses and session URLs that do not belong on a public page. A test
  asserts the rendered page contains no address, URL, or commit trailer.
- **Visitor counter, counted on the server.** `web/api/index.js` substitutes the
  count into the HTML before it is sent, so the browser makes no extra request
  and `connect-src 'none'` still holds. A single integer is stored: no IP
  address, user agent, per-visitor row, or timestamp. If the datastore is
  unconfigured or unreachable the page is served exactly as normal with the
  counter absent, so it can never take the site down.

### Fixed
- **The browser build was not reproducible across Python versions.** The digit
  table added in 2.0.0 was derived by asking the running interpreter which code
  points `str.isdigit()` accepts, and that set grows with each Unicode release:
  a machine on Unicode 15.0 emitted two ranges (Kawi and Nag Mundari digits)
  that a machine on 14.0 did not, so the committed page depended on who built
  it and the CI staleness gate failed. The table is now frozen at the pinned
  Unicode version alongside the default-ignorable data, and `_note` reads from
  it rather than from `str.isdigit()`, so the CLI and the browser agree on
  every interpreter. A test asserts the frozen table is never behind the
  running Python.
- **The security headers the meta CSP cannot carry are now sent for real.**
  `web/vercel.json` sets `Content-Security-Policy: frame-ancestors 'none'`,
  which is ignored in a `<meta>` element and was therefore providing no
  clickjacking protection at all on the hosted copy, plus
  `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and the
  cross-origin isolation headers. This closes the last audit finding that could
  only be fixed at the deployment layer.
- **Keyboard focus was invisible on the new switches.** Their real checkbox is
  visually hidden, so the focus ring was being drawn on an element nobody could
  see. Found by an automated browser pass, not by eye.
- **Content could scroll underneath the sticky header** and become unclickable;
  the document now reserves scroll padding for it.
- Browser copy said "five categories" where the implementation has six, and
  still stated a vendor watermark attribution as settled fact. Both were
  corrected in the README in 2.0.0 but missed in the page itself.

### Changed
- The CI staleness gate now diffs the whole `web/` directory rather than
  `index.html` alone, so a stale generated patch-notes page fails the build.

## 2.0.0
Completes the external engineering audit backlog: the remaining product,
forensic, and polish items on top of the 1.7.0 hardening pass. Major version
because two behaviours changed in ways a script could notice; see Migration.

### Added
- **Severity model.** Every hit is now rated `info`, `low`, `medium`, or
  `high`. Annotated likely-legitimate uses (BOM at file start, emoji ZWJ,
  presentation selectors, French spacing, digit grouping) are `info`; bidi
  embeddings/overrides/isolates and the Tags block are `high`. New
  `--min-severity LEVEL` and `--suspicious-only` (shorthand for
  `--min-severity medium`). The filter narrows *scope*, not just display: the
  exit code and `--strip` follow it, so `--suspicious-only --strip` is a
  conservative cleanup that will not break emoji sequences. JSON gains a
  `severity` field per hit and a top-level `min_severity`, both additive.
- **Forensic mode.** `--include-default-ignorables` enables a seventh, opt-in
  `default-ignorable` category covering every remaining Unicode
  `Default_Ignorable_Code_Point`, including reserved ranges. Off by default so
  the curated taxonomy keeps its signal-to-noise ratio.
- **Specification oracle.** A frozen `Default_Ignorable_Code_Point` table
  (pinned Unicode version, independent of the running interpreter) is now the
  reference the curated taxonomy is tested against. Parity proves Python and
  JavaScript agree; it cannot prove the shared taxonomy is complete, which is
  how U+180F stayed missing. A conformance test now asserts the exact set of
  documented gaps, so a future omission fails a test instead of passing
  silently.
- `--force` to overwrite an existing `FILE.clean.EXT`.
- `tools/benchmark.py`, a non-gating harness reporting wall-clock and peak
  memory across ordinary, newline-dense, mostly-hidden, and mixed-Unicode
  corpora.
- A man page and bash/zsh completions, generated from the argparse parser by
  `tools/build_docs.py` and diff-gated in CI, so a new flag cannot ship with
  stale docs.

### Fixed
- **U+180F was named inconsistently across Python versions.** Its name was
  resolved through `unicodedata`, but the code point was added in Unicode 14.0,
  so on Python 3.9/3.10 (which bundle Unicode 13.0) the lookup missed and fell
  back to a generic label while the generated browser build reported the real
  name. The Mongolian free variation selectors are now named from an explicit
  table. Introduced in 1.7.0.
- **Browser and CLI advisory notes could disagree on digits.** The browser
  approximated Python's `str.isdigit()` with the `Nd`/`No` Unicode categories,
  which is wrong in both directions: U+00BC is `No` but not a digit, and 128
  digits are outside `Nd`. An exact range table is now generated from CPython,
  and the parity suite covers the edge cases.
- Backup creation no longer has a check-then-write race: the `.bak` name is
  claimed with an atomic exclusive create, so two concurrent runs cannot both
  conclude no backup exists.
- Atomic writes now fsync the containing directory, so the rename itself is
  durable and not just the file contents.
- `--in-place` on stdin, a repeated `-` source, `--force` without `--strip`, and
  `--suspicious-only` combined with `--min-severity` are now rejected with a
  clear message instead of being silently ignored or ambiguous.
- The browser page no longer lists `frame-ancestors` in its meta CSP. The spec
  ignores that directive when the policy is delivered in a `<meta>` element, so
  listing it implied a clickjacking protection that never existed. It is now
  documented as an HTTP response header instead. `connect-src 'none'`, which is
  what backs the privacy claim, is unchanged and remains effective.

### Changed (breaking)
- **`--strip` no longer silently overwrites an existing `FILE.clean.EXT`.** It
  refuses with exit code 2. This matches the existing `.bak` behaviour, where
  refusing to clobber is already the rule.
  *Migration*: pass `--force` to restore the old overwrite behaviour.
- **A closed pipe is no longer reported as success.** `BrokenPipeError` used to
  be caught and turned into exit 0, so `markcheck f.md | head` claimed success
  even when hidden characters were found. On POSIX, markcheck now uses default
  SIGPIPE handling and terminates with the conventional 141; on Windows, the
  fallback path returns 2 rather than 0.
  *Migration*: a pipeline that relied on exit 0 from a truncated run should
  check for 141, or avoid closing the pipe early.

### Documentation
- Performance claims are now backed by `tools/benchmark.py` and stated
  honestly: ~3.4x input size in peak memory for ordinary prose with sparse
  hits, but that is not a bound — pathological hidden-heavy input reaches ~140x
  uncapped, and `--max-hits` is what bounds the worst case. Throughput is
  hardware-dependent and quoted as a measured range.
- Vendor attribution wording softened: markcheck no longer restates any
  vendor's explanation of a watermark or training artifact as settled fact, and
  points readers to first-party sources.
- Documented the metadata boundary of atomic replacement (permission bits are
  preserved; ownership, timestamps, ACLs, and xattrs are not).

## 1.7.0
Hardening release from an external engineering audit. No redesign; the
architecture, scope, and zero-dependency model are unchanged. Fixes several
reproducible output-contract, encoding, resource, and Unicode-coverage defects.

- **Output contract.** `--strip --stdout` now writes the cleaned document to
  stdout and *only* that; the human report goes to stderr. Previously the
  report was printed to stdout first, so `... --strip --stdout > clean.txt`
  captured the report plus the cleaned text. Redirecting stdout now yields the
  cleaned bytes exactly. New tests assert exact stdout equality, not just
  substring containment.
- **Output contract.** `--json` and `--stdout` are now rejected as mutually
  exclusive. The combination wrote cleaned text and then a JSON payload to the
  same stream, producing output that was neither valid JSON nor a clean
  document.
- **Encoding fidelity.** UTF-16/UTF-32 byte order is now preserved exactly. The
  decoder records the precise byte order (`utf-16-le`/`-be`, `utf-32-le`/`-be`)
  instead of the generic family, so re-encoding no longer flips a big-endian
  document to the platform's native little-endian on the way out.
- **Backup fidelity.** With `--in-place`, the `.bak` backup is now a
  byte-for-byte copy of the original file rather than a re-encode of the
  decoded text, so it is a faithful image regardless of source encoding.
- **Error status.** A refused write — declining to overwrite an existing
  `.bak` — now exits with code 2 instead of leaving the exit code based only on
  whether hidden characters were found. A script can now tell the requested
  cleanup did not happen.
- **Resource safety.** `scan()` now tracks line and column incrementally
  instead of building a list of every newline offset and binary-searching it.
  On newline-heavy input the old list of Python integers could consume many
  times the input size before any hit was stored; the streaming pass removes
  that amplification and simplifies the code.
- **Resource safety.** `--max-bytes` is now enforced at the actual read
  boundary for files (read at most `max_bytes + 1`), not only via a
  `getsize()` precheck that a growing file or a special file could defeat.
- **Unicode coverage.** U+180F MONGOLIAN FREE VARIATION SELECTOR FOUR is now
  detected. It is an invisible variation selector in the stated threat class
  and was previously missed by both the Python and the browser builds.
- **Browser resource safety.** The browser scan now caps stored hit records
  (mirroring the Python `total`/stored/`capped` model) so a very large paste
  that is mostly hidden characters cannot grow an unbounded array in the tab.
  The reported total stays exact.
- Docs: corrected the category count (six, not five), documented the byte-order
  and byte-for-byte backup guarantees.
- Tests: added exact-equality output-contract tests, explicit BE/LE encoding
  fixtures, an FVS4 detection test, a bounded-read test, and replaced bare file
  `open()` calls with context managers.

## 1.6.0
- Fix a false annotation: a NO-BREAK SPACE or NARROW NO-BREAK SPACE at the end
  of the text was labeled "French-style punctuation spacing (likely
  legitimate)". An empty string is a substring of every string in Python, so
  the membership test matched when there was no following character at all.
  A trailing hidden space is exactly where a watermark would sit, so this
  annotation was actively misleading. Found by differential testing against
  the new browser build.
- Add a browser version at `web/index.html`. Paste text, see what is hiding in
  it. Runs entirely client side; no text is uploaded, stored, or logged.
- Add `tools/build_web.py`, which generates the browser build from
  markcheck.py so the two cannot drift, and `tools/check_parity.py`, which
  proves across 1519 cases that the JavaScript reports the identical hits,
  positions, names, notes, and stripped output as the Python.
- CI now runs the parity check and fails if the committed web build is stale.
- Expand packaging metadata (authors, classifiers, changelog URL) and add a
  .gitignore.
- README: quickstart above the fold, and install paths that do not require
  cloning first.
- Browser build polish: a Content-Security-Policy that enforces the privacy
  claim technically (`connect-src 'none'` means the page cannot phone home
  even if it wanted to), a no-referrer policy, a noscript message, an
  aria-live results region, and a horizontally scrolling results table on
  narrow screens.
- Browser build performance: the inline preview is capped at 8,000 characters
  and typing is debounced, so a large document no longer rebuilds the whole
  DOM on every keystroke. Counts and the results table still describe the
  entire text, and the truncation is stated on screen. A pathological input
  of 30,000 hidden characters used to generate roughly 900 KB of markup; it
  now generates 8 KB.

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
