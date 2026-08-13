#!/usr/bin/env python3
"""Prove the browser build agrees with markcheck.py, character for character.

Generates a randomized corpus plus targeted edge cases, records what the
Python module reports for each, then runs the generated JavaScript over the
same corpus under Node and compares every field of every hit. Any drift
between the two implementations fails loudly.

Requires Node. Skips with a clear message if Node is absent.

Usage: python3 tools/check_parity.py
"""
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import markcheck as m  # noqa: E402

CASES = 1500
SEED = 20260813

EDGE_CASES = [
    "", "\ufeffhi", "\U0001f468\u200d\U0001f469", "\u2764\ufe0f", "a\ufe0f",
    "Non\u202f!", "10\u00a0000", "word\u202fword",
    "\u00ab\u202fOui\u202f\u00bb",
    "a\r\nb\r\nx\u200b", "hi \U0001F600\nz\u200b", "10\u00a0km",
    "a\u2028b",
    "trailing nnbsp\u202f", "trailing nbsp\u00a0", "\u0661\u00a0\u0662",
    "\n\n\u200b", "\u200b" * 40, "plain ascii text with no hits at all",
]


def corpus():
    tracked = (list(m._SINGLE) + list(m._WHITESPACE)
               + list(range(0x180B, 0x180E)) + list(range(0xFE00, 0xFE10))
               + list(range(0xE0100, 0xE0110)) + [0xE0001]
               + list(range(0xE0020, 0xE0080)))
    pool = (list("the quick brown fox 0123 \n\t.,!?;:%")
            + ["\u00ab", "\u00bb", "\u4e2d", "\U0001F600", "\U0001F468",
               "\u2764"]
            + [chr(c) for c in tracked])
    rng = random.Random(SEED)
    out = []
    for _ in range(CASES):
        out.append("".join(rng.choice(pool)
                           for _ in range(rng.randint(0, 70))))
    return out + EDGE_CASES


def python_reference(texts):
    cats = set(m.CATEGORIES)
    ref = []
    for text in texts:
        hits = m.scan(text, cats).hits
        ref.append({
            "hits": [[h["index"], h["line"], h["column"], h["codepoint"],
                      h["name"], h["category"], h["note"]] for h in hits],
            "stripped": m.strip_hidden(text, cats),
        })
    return ref


HARNESS = r"""
const fs = require("fs");
const page = fs.readFileSync(process.argv[2], "utf8");
const start = page.indexOf("const T = {");
const end = page.indexOf("const ALL = new Set");
if (start < 0 || end < 0) {
  console.error("ENGINE_NOT_FOUND");
  process.exit(3);
}
const engine = page.slice(start, end);
const api = new Function(engine + "\nreturn {T, scan, stripHidden};")();
const data = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const ALL = new Set(api.T.CATEGORIES);
const bad = [];
data.corpus.forEach((text, k) => {
  const want = data.ref[k];
  const got = api.scan(text, ALL).map(h => [h.index, h.line,
    h.column, h.codepoint, h.name, h.category, h.note]);
  if (JSON.stringify(got) !== JSON.stringify(want.hits)) {
    bad.push({case: k, kind: "scan", text, want: want.hits, got});
  }
  const stripped = api.stripHidden(text, ALL);
  if (stripped !== want.stripped) {
    bad.push({case: k, kind: "strip", text,
              want: want.stripped, got: stripped});
  }
});
console.log(JSON.stringify({checked: data.corpus.length,
  mismatches: bad.slice(0, 5), total: bad.length}));
"""


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP: Node is not installed; cannot verify browser parity.")
        return 0

    page = os.path.join(ROOT, "web", "index.html")
    if not os.path.exists(page):
        print("FAIL: web/index.html is missing. Run tools/build_web.py.")
        return 1

    version = re.search(r"markcheck (\d+\.\d+\.\d+)", open(
        page, encoding="utf-8").read())
    if not version or version.group(1) != m.__version__:
        found = version.group(1) if version else "none"
        print(f"FAIL: web build is version {found}, module is "
              f"{m.__version__}. Run tools/build_web.py.")
        return 1

    texts = corpus()
    payload = {"corpus": texts, "ref": python_reference(texts)}
    with tempfile.TemporaryDirectory() as d:
        data_path = os.path.join(d, "parity.json")
        harness = os.path.join(d, "harness.js")
        with open(data_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        with open(harness, "w", encoding="utf-8") as fh:
            fh.write(HARNESS)
        proc = subprocess.run([node, harness, page, data_path],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        print("FAIL: harness error:", proc.stderr.strip()[:400])
        return 1

    result = json.loads(proc.stdout)
    if result["total"]:
        print(f"FAIL: {result['total']} mismatch(es) between markcheck.py "
              f"and the browser build.")
        for bad in result["mismatches"]:
            print(" ", json.dumps(bad)[:300])
        return 1
    print(f"OK: {result['checked']} cases, browser build matches "
          f"markcheck {m.__version__} exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
