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
  if ((cp >= 0x180B && cp <= 0x180D) || cp === 0x180F) {
    const words = { 0x180B: "ONE", 0x180C: "TWO", 0x180D: "THREE",
                    0x180F: "FOUR" };
    return { name: "MONGOLIAN FREE VARIATION SELECTOR " + words[cp],
             category: "variation-selector" };
  }
  const tag = T.TAGS[cp];
  if (tag) return { name: tag, category: "tag" };
  const w = T.WS[cp];
  if (w) return { name: w, category: "whitespace" };
  return null;
}

// Mirrors markcheck._note. isDigit approximates Python str.isdigit via the
// Unicode Nd and No properties; the difference affects an advisory note only,
// never whether a character is reported.
function isDigit(ch) { return ch !== "" && /[\p{Nd}\p{No}]/u.test(ch); }

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
function scan(text, categories, maxHits) {
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
      total += 1;
      if (maxHits && hits.length >= maxHits) {
        capped = true;
      } else {
        hits.push({ index: i, line: line, column: col, char: ch,
                    codepoint: cp,
                    codepointHex: "U+" + cp.toString(16).toUpperCase()
                      .padStart(4, "0"),
                    name: info.name, category: info.category,
                    note: note(chars, i, cp) });
      }
    }
    if (ch === "\n") { line += 1; col = 0; }
  }
  return { hits: hits, total: total, capped: capped };
}

function stripHidden(text, categories) {
  let out = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0);
    const info = classify(cp);
    if (!info || !categories.has(info.category)) { out += ch; }
    else { out += (T.REPL[cp] !== undefined ? T.REPL[cp] : ""); }
  }
  return out;
}
