// GENERATED FROM markcheck.py. Do not edit by hand.
// Regenerate with tools/build_web.py so the browser and the CLI cannot drift.
const T = __TABLES__;

function pictographic(cp) {
  for (const [lo, hi] of T.PICTO) { if (cp >= lo && cp <= hi) return true; }
  return false;
}

function classify(cp) {
  const s = T.SINGLES[cp];
  if (s) return { name: s[0], category: s[1] };
  if ((cp >= 0xFE00 && cp <= 0xFE0F) || (cp >= 0xE0100 && cp <= 0xE01EF)) {
    const n = cp <= 0xFE0F ? cp - 0xFE00 + 1 : cp - 0xE0100 + 17;
    return { name: "VARIATION SELECTOR-" + n, category: "variation-selector" };
  }
  // Mongolian free variation selectors. U+180E (VOWEL SEPARATOR) falls in
  // this span but is handled by T.SINGLES above, so it is skipped here.
  const fvs = T.FVS[cp];
  if (fvs) return { name: fvs, category: "variation-selector" };
  const tag = T.TAGS[cp];
  if (tag) return { name: tag, category: "tag" };
  const w = T.WS[cp];
  if (w) return { name: w, category: "whitespace" };
  if (inRanges(cp, T.DI)) {
    return { name: T.DI_NAME, category: "default-ignorable" };
  }
  return null;
}

function inRanges(cp, ranges) {
  let lo = 0, hi = ranges.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (cp < ranges[mid][0]) { hi = mid - 1; }
    else if (cp > ranges[mid][1]) { lo = mid + 1; }
    else { return true; }
  }
  return false;
}

// Mirrors markcheck.severity.
function severity(cp, category, note) {
  if (note) return "info";
  if (category === "tag" || inRanges(cp, T.HIGH_BIDI)) return "high";
  if (category === "whitespace") return "low";
  if (category === "default-ignorable") return "low";
  return "medium";
}

// Mirrors markcheck._note. isDigit reproduces Python str.isdigit exactly, from
// a range table generated off CPython itself: \p{Nd} alone misses the 128
// digits outside that category, and \p{Nd}|\p{No} over-matches (U+00BC VULGAR
// FRACTION ONE QUARTER is No, but not a digit).
function isDigit(ch) {
  return ch !== "" && inRanges(ch.codePointAt(0), T.DIGITS);
}

function note(chars, i, cp) {
  if (i === 0 && cp === 0xFEFF) return "BOM at file start (conventional)";
  if (cp === 0x200D) {
    const prev = i ? chars[i - 1].codePointAt(0) : -1;
    const nxt = i + 1 < chars.length ? chars[i + 1].codePointAt(0) : -1;
    if (pictographic(prev) && pictographic(nxt)) {
      return "joins two emoji (likely legitimate)";
    }
  }
  if (cp === 0xFE0E || cp === 0xFE0F) {
    const prev = i ? chars[i - 1].codePointAt(0) : -1;
    if (pictographic(prev)) {
      return "emoji presentation selector (likely legitimate)";
    }
  }
  if (cp === 0x00A0 || cp === 0x202F) {
    const prev = i ? chars[i - 1] : "";
    const nxt = i + 1 < chars.length ? chars[i + 1] : "";
    if (":;!?\u00BB%".includes(nxt) && nxt !== "") {
      return "French-style punctuation spacing (likely legitimate)";
    }
    if (prev === "\u00AB") {
      return "French-style punctuation spacing (likely legitimate)";
    }
    if (isDigit(prev) && isDigit(nxt)) return "digit grouping (likely legitimate)";
  }
  return "";
}

// Iterate by code point, matching Python string indexing on astral characters.
// Returns { hits, total, capped }, mirroring Python's ScanResult: total is the
// true count, hits holds at most maxHits records so a paste that is mostly
// hidden characters cannot grow an unbounded array in the tab.
function scan(text, categories, maxHits, minSeverity) {
  const threshold = T.SEVERITIES.indexOf(minSeverity || "info");
  const chars = Array.from(text);
  const hits = [];
  let total = 0, capped = false;
  let line = 1, col = 0;
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    col += 1;
    const cp = ch.codePointAt(0);
    const info = classify(cp);
    if (info && categories.has(info.category)) {
      const n = note(chars, i, cp);
      const level = severity(cp, info.category, n);
      if (T.SEVERITIES.indexOf(level) >= threshold) {
        total += 1;
        if (maxHits && hits.length >= maxHits) {
          capped = true;
        } else {
          hits.push({ index: i, line: line, column: col, char: ch,
                      codepoint: cp,
                      codepointHex: "U+" + cp.toString(16).toUpperCase()
                        .padStart(4, "0"),
                      name: info.name, category: info.category,
                      severity: level, note: n });
        }
      }
    }
    if (ch === "\n") { line += 1; col = 0; }
  }
  return { hits: hits, total: total, capped: capped };
}

function stripHidden(text, categories, minSeverity) {
  const threshold = T.SEVERITIES.indexOf(minSeverity || "info");
  const chars = Array.from(text);
  let out = "";
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    const cp = ch.codePointAt(0);
    const info = classify(cp);
    if (!info || !categories.has(info.category)) { out += ch; continue; }
    if (threshold) {
      const level = severity(cp, info.category, note(chars, i, cp));
      if (T.SEVERITIES.indexOf(level) < threshold) { out += ch; continue; }
    }
    out += (T.REPL[cp] !== undefined ? T.REPL[cp] : "");
  }
  return out;
}
