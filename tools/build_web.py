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
import re
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
    """The frozen digit table markcheck._note uses.

    Emitted from the module constant rather than derived from the running
    interpreter. str.isdigit() gains code points with each Unicode release, so
    generating it here would make the committed build differ depending on which
    Python built it, and the CI staleness gate would fail on a machine one
    Unicode version ahead of the last person to run this.
    """
    return [list(r) for r in m._DIGIT_RANGES]


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


def _escape(text):
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))


def _inline(text):
    """Render the inline markdown subset the changelog actually uses.

    Escaping happens first and formatting second, so nothing in CHANGELOG.md
    can inject markup. Code spans are lifted out before the bold and italic
    passes and put back afterwards, so an asterisk inside `--flag` stays
    literal.
    """
    text = _escape(text)
    spans = []

    def stash(match):
        spans.append(match.group(1))
        return "\x00%d\x00" % (len(spans) - 1)

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00",
                  lambda m: "<code>%s</code>" % spans[int(m.group(1))], text)


def changelog_html(markdown):
    """Turn CHANGELOG.md into the body of the patch-notes page.

    Only CHANGELOG.md is ever read. Git metadata is deliberately not a source:
    commit trailers carry co-author addresses and session URLs that have no
    business on a public page.
    """
    out = []
    items = []
    para = []

    def flush():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
            para.clear()
        if items:
            out.append("<ul>%s</ul>" %
                       "".join("<li>%s</li>" % _inline(" ".join(li))
                               for li in items))
            items.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush()
        elif stripped.startswith("# "):
            flush()
        elif stripped.startswith("## "):
            flush()
            if out:
                out.append("</section>")
            version = _escape(stripped[3:])
            out.append('<section class="card glass release">'
                       '<h2><span class="ver">%s</span></h2>' % version)
        elif stripped.startswith("### "):
            flush()
            label = stripped[4:]
            cls = " danger" if "breaking" in label.lower() else ""
            out.append('<h3 class="tagline%s">%s</h3>' % (cls, _escape(label)))
        elif stripped.startswith("- "):
            if para:
                flush()
            items.append([stripped[2:]])
        elif items and raw.startswith("  "):
            # A wrapped continuation of the list item above it.
            items[-1].append(stripped)
        else:
            if items:
                flush()
            para.append(stripped)
    flush()
    if out:
        out.append("</section>")
    return "\n".join(out)


def build_changelog():
    body = changelog_html(
        open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read())
    page = open(os.path.join(HERE, "changelog.template.html"),
                encoding="utf-8").read()
    out = page.replace("__BODY__", body).replace("__VERSION__", m.__version__)
    dest = os.path.join(ROOT, "web", "changelog.html")
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(out)
    return dest, len(out)


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
    path, size = build_changelog()
    print(f"wrote {path} ({size} bytes) from CHANGELOG.md")
