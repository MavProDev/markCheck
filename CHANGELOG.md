# Changelog

## 2.4.4
### Fixed
- **The about and changelog pages scrolled sideways on a narrow phone.** Their
  header carries a wordmark, two links and the theme toggle, which at 320px is
  a few pixels wider than the screen — so the toggle hung off the right edge
  and dragged the whole page into a horizontal scroll. The scanner page escaped
  it only by accident, because it hides its command-palette button below 560px.
  The header now tightens its spacing at narrow widths, which reclaims far more
  than the few pixels needed without dropping any control.
- Found by rendering all three pages at 320px rather than by reading the CSS;
  2px and 3px offsets are not the kind of thing that shows up in a diff.

## 2.4.3
### Fixed
- **2.4.2 could not deploy.** Its `vercel.json` carried a `"//"` key holding an
  explanation of the redirect rule. JSON has no comments, and Vercel validates
  the file against a strict schema that rejects any property it does not
  recognise, so every deployment failed — preview and production alike. The
  live site was never broken; it kept serving the previous build, which meant
  the failure was invisible from the outside and the 2.4.2 fix never reached
  anyone.
- The rationale now lives in `web/api/index.js`, next to the failure path that
  depends on it, where a comment is actually legal.

### Added
- `TestDeploymentRoutes` now checks every route object against the set of
  properties Vercel accepts. The rest of the suite proved the routing was
  *correct* while the file it lived in would not parse — a deploy-time failure
  that no amount of behavioural testing could have caught.

## 2.4.2
### Fixed
- **The visit counter vanished after navigating scanner to about and back.**
  The about and changelog pages link to the scanner as a relative
  `index.html`, which is what keeps them navigable when the pages are opened
  from disk. On the deployed site that path was served straight off the
  filesystem, skipping the function that substitutes the count — so the
  placeholder arrived in the browser as an inert HTML comment and the counter
  simply was not there. `/index.html` now permanently redirects to `/`, which
  also matches the `og:url` and canonical tags, since those have always named
  `/` and never `/index.html`.
- That redirect created a loop the fix had to close as well: the function's
  own failure path redirected to `/index.html`, which now comes back to `/`
  and lands in the function again. A missing bundle is a broken deploy rather
  than a runtime failure worth papering over, so it now answers directly with
  a small self-contained page pointing at the command line tool.

### Added
- `TestDeploymentRoutes` reads `web/vercel.json` and checks that `/` still
  reaches the function, that `/index.html` permanently redirects to `/`, that
  the redirect is ordered ahead of the filesystem handler, and that the
  relative link the redirect exists for is still in the templates. Nothing
  else in the suite looked at the route table.
- `tools/check_api.js` now covers the missing-document path and asserts it
  sends no `Location` header at all.

## 2.4.1
### Changed
- **The visit counter is redrawn as a 1950s tachometer.** The first attempt was
  a neon dial that read as cheap against a page built on restraint. It is now a
  Smiths-style instrument: a vanilla face with a printed scale, subdivided minor
  marks, a polished bezel, a tapered red pointer with its counterweight tail,
  and a domed crystal throwing a highlight across the upper left. Each digit
  sits under its own glass dome, the way an odometer reads through a curved
  window.
- The final decade of the scale is printed as a **redline**, so a millionth
  visit puts the needle into it. The scale itself is unchanged: still
  logarithmic, still one major mark per decade.
- The dial colours are deliberately **not themed**. A physical instrument does
  not repaint itself when the room lights change, so the cream face is constant
  in light and dark and reads as an object set into the page rather than part
  of its chrome. Only the caption follows the theme, because it is printed on
  the page and not on the dial.
- Minor marks sit at 8 degrees, five to a decade. Like the 40-degree major
  spacing, 8 divides 360 exactly, so the subdivision closes cleanly with no
  stray partial mark where the scale meets the gap.

### Notes
- The instrument tokens moved out of `tools/shared.css`, which the scanner page
  does not read, and into the page that actually uses them. The guard added in
  2.4.0 now checks the base `:root` rather than every theme block, which is the
  correct invariant for a colour that is intentionally theme-invariant.

## 2.4.0
### Added
- **The visit counter is now an instrument.** It was the least considered
  element on a page otherwise built with care: a small grey pill. It is now a
  tachometer whose needle tracks the **order of magnitude** of the count rather
  than the count itself — one major tick per decade, six decades to full scale.
  A linear gauge would sit pinned at zero through the site's first few thousand
  visitors and pinned at full ever after; this one is legible at six visits and
  at a million, and never needs rescaling.
- The dial geometry is chosen so the arithmetic is exact rather than
  approximately right: a 240 degree sweep across six decades is 40 degrees per
  decade, and 40 divides 360, so the tick bezel repeats cleanly the whole way
  round with no masking needed to hide stray marks in the gap at the bottom.
- Digits sit in individual cells the way an odometer drum reads, with an
  electric-aqua glow and cap. The whole instrument is a single `role="img"`
  carrying one sentence, so assistive technology is given a coherent statement
  instead of a gauge followed by loose digits.
- The counter is still substituted into the document on the server. Nothing
  about it fetches anything, and `connect-src 'none'` is untouched.

### Fixed
- **`--strip` produced wrong filenames for dotfiles and for names ending in a
  dot.** `.env` became `.clean.env`, burying the original name, and `notes.`
  became `notes.clean.` — a filename Windows cannot represent at all, on a
  project that tests on Windows. A dot alone does not make an extension: a
  leading dot is part of the name, and a trailing dot leaves nothing after it.
  Both now fall back to appending the suffix. `.env` becomes `.env.clean`.
- The command palette's input was labelled only by its placeholder and had no
  combobox semantics, so arrow-key selection moved the highlight visually while
  telling assistive technology nothing. It now carries a label, the combobox
  role, and an `aria-activedescendant` that tracks the selection. The "no
  matching command" row no longer claims to be a selectable option.
- The deployment function substituted the count with a replacement *string*,
  which `String.replace` scans for `$&` and friends. Nothing it emits contains
  a dollar sign, but that was a property of the current copy rather than a
  guarantee; it now uses a function replacement.

### Notes
- `tools/shared.css` described itself as the single source of design tokens for
  all three pages. It is not: the scanner page is assembled by a different path
  and keeps its own palette. The comment has been corrected, and the two are
  now held together by a test that fails if any token defined in both
  disagrees, rather than by the discipline that had been holding them.
- CI now syntax-checks the JavaScript. It had none: a parse error in the
  deployment function would have reached production and failed *silently*
  there, since that function is deliberately built to swallow its own errors.

## 2.3.1
### Changed
- **The visitor counter is live.** The code shipped in 2.2.1; what was missing
  was the storage behind it, which is now provisioned. The count is still
  resolved on the server and substituted into the document before it is sent,
  so the page continues to make zero network requests and `connect-src 'none'`
  is untouched.
- The counter's credential is now a **publishable** key, and the environment
  variable is named `SUPABASE_KEY` rather than `SUPABASE_SERVICE_KEY` to say
  so honestly. The increment runs through a `SECURITY DEFINER` function, so the
  key needs no privilege beyond `EXECUTE` on that one function — it cannot read
  the table it increments. A service key would have granted the deployment full
  access to the database in order to add one to a number.
- The key is sent on the `apikey` header alone. Publishable keys are not JWTs,
  so repeating one in `Authorization: Bearer` makes the gateway reject the call
  as a malformed token. That failure would have been invisible: the function
  swallows storage errors by design and serves the page with the counter
  hidden, which is indistinguishable from not being configured at all.
- Stored data is unchanged and remains a single integer in a single row. The
  table has row level security enabled with no policies **and** the default API
  grants revoked, so it is unreachable through the API by either route.

### Added
- `tools/check_api.js` now pins the request shape sent to storage — endpoint,
  method, and the presence of `apikey` with the absence of `Authorization`.
  Nothing else in the suite could catch that regression, because the function
  is built never to report one.

### Security
- The hosted copy now sends `Strict-Transport-Security`, joining the existing
  `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and the cross-origin isolation headers. A first visit
  over plain HTTP could previously have been intercepted before the redirect.
- `.gitignore` now covers `.env` files. Nothing in this project reads one; the
  patterns exist so that a local file holding deployment credentials cannot be
  staged by accident.
- Audited alongside this release, with results recorded rather than assumed:
  the escaping in front of every `innerHTML` in the scanner was tested against
  eight classes of injection payload — including attribute breaks on both quote
  styles and a payload wrapped in a bidirectional control — with none executing,
  none producing a DOM node, and no network request attempted under attack.
  This matters because the page's policy permits inline handlers, so an
  escaping miss would be script execution rather than a cosmetic bug.

## 2.3.0
### Added
- **Social preview cards.** A link to the site shared as a bare URL with no
  title, summary, or image. All three pages now carry Open Graph and Twitter
  metadata plus a canonical URL, and `web/og.png` is the card: a lit glass
  panel over a coloured aura, carrying the headline and a line of ordinary
  prose with two invisible characters caught in the act — a narrow no-break
  space and a zero-width space, flagged mid-sentence where they actually hide.
  Composed to survive being viewed at a third of its size in a feed.
- The card is authored in HTML and CSS (`tools/og.template.html`) and rendered
  to a PNG at build time by `tools/build_og.js`, using the browser this
  repository already drives for verification. Vercel's `@vercel/og` was the
  obvious alternative and was rejected deliberately: it generates images per
  request, which earns its keep when card content varies per URL. Three static
  pages whose cards never change would gain a dependency, a `node_modules`, and
  a cold start per crawler hit to produce the same image forever — and put a
  supply chain inside a tool whose about page claims it has none.
- The canonical host now lives in exactly one place, `build_web.SITE_URL`. The
  pages remain otherwise host-agnostic and every internal link stays relative.

### Notes
- `web/og.png` is the one generated file CI cannot rebuild, because the runners
  have no browser. It is therefore not diff-gated and is regenerated on demand
  when the card design changes. A deliberate exception to this project's
  generate-and-gate rule, recorded here rather than left to be discovered.
- The card carries its own copy of the palette, since it renders standalone
  with no cascade from the site. `build_og.js` fails the build if those colours
  drift from `tools/shared.css`.
- Verified in a real browser: adding `og:image` does not cause the page to
  fetch anything. Crawlers read the tag and fetch the image server-side, so the
  `connect-src 'none'` guarantee is untouched and the no-network assertion
  still passes on all three pages.

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
