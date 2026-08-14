#!/usr/bin/env python3
"""Generate web/index.html from markcheck.py.

The browser build must never be edited by hand. Its character tables and
classification logic are generated from the Python module so that the two
implementations cannot drift apart. Run tools/check_parity.py afterwards to
prove they still agree.

Usage: python3 tools/build_web.py
"""
import json
import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import markcheck as m  # noqa: E402


def _ranges(codepoints):
    """Compress a sorted iterable of code points into [lo, hi] ranges."""
    out = []
    for cp in codepoints:
        if out and cp == out[-1][1] + 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return out


def digit_ranges():
    """Every code point where Python's str.isdigit() is True.

    Generated from the interpreter rather than approximated in JavaScript with
    Unicode general categories, so the browser's advisory digit-grouping note
    matches markcheck.py exactly (see _note).
    """
    return _ranges(cp for cp in range(0x110000) if chr(cp).isdigit())


def tables():
    tags = {cp: unicodedata.name(chr(cp), "TAG CHARACTER")
            for cp in [0xE0001] + list(range(0xE0020, 0xE0080))}
    return {
        "SINGLES": {str(k): [v[0], v[1]]
                    for k, v in sorted(m._SINGLE.items())},
        "WS": {str(k): v for k, v in sorted(m._WHITESPACE.items())},
        "TAGS": {str(k): v for k, v in sorted(tags.items())},
        "FVS": {str(k): v for k, v in sorted(m._MONGOLIAN_FVS.items())},
        "REPL": {str(k): v for k, v in sorted(m._STRIP_REPLACEMENT.items())},
        "CATEGORIES": list(m.CATEGORIES),
        "DEFAULTS": list(m.DEFAULT_CATEGORIES),
        "DESCRIPTIONS": dict(m.CATEGORIES),
        "PICTO": [list(p) for p in m._PICTO_RANGES],
        "SEVERITIES": list(m.SEVERITIES),
        "HIGH_BIDI": _ranges(sorted(m._HIGH_BIDI)),
        "DI": [list(r) for r in m.DEFAULT_IGNORABLE],
        "DI_NAME": m._DEFAULT_IGNORABLE_NAME,
        "DIGITS": digit_ranges(),
        "UNICODE_VERSION": m.UNICODE_VERSION,
        "VERSION": m.__version__,
    }


def build():
    engine = open(os.path.join(HERE, "engine.template.js"),
                  encoding="utf-8").read()
    engine = engine.replace(
        "__TABLES__", json.dumps(tables(), separators=(",", ":")))
    page = open(os.path.join(HERE, "page.template.html"),
                encoding="utf-8").read()
    out = page.replace("__ENGINE__", engine).replace(
        "__VERSION__", m.__version__)
    dest = os.path.join(ROOT, "web", "index.html")
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    return dest, len(out)


if __name__ == "__main__":
    path, size = build()
    print(f"wrote {path} ({size} bytes) from markcheck {m.__version__}")
