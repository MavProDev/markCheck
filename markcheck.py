#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Scan text for hidden and invisible Unicode characters.

Detects zero-width characters, bidirectional controls, variation selectors,
nonstandard whitespace, and the Unicode Tags block: code points that render
as nothing, or as an ordinary-looking space, yet occupy distinct bytes. These
are used for text watermarking, steganographic payloads, and Trojan-Source
style attacks (CVE-2021-42574).

Scope. markcheck inspects the byte stream, so it finds marks that ARE bytes.
It does not detect statistical (token-distribution) watermarks, which bias a
model's word choice and leave nothing hidden in the text. It does not read
C2PA provenance metadata, which lives in the binary container of image and
PDF files; use a C2PA tool such as c2patool, or exiftool, for those.

It is source-agnostic. There is no allow/deny list tied to any vendor.
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
import tempfile
import unicodedata
from collections import Counter, namedtuple

__version__ = "1.5.0"

DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB
DEFAULT_MAX_HITS = 200_000

# hits: stored records (may be capped); total: true count; capped: bool
ScanResult = namedtuple("ScanResult", "hits total capped")

CATEGORIES = {
    "zero-width": "Zero-advance invisibles (ZWSP, ZWJ, ZWNJ, word joiner, "
                  "invisible math operators, BOM). ZWJ is also a valid emoji "
                  "and Indic joiner; likely-legitimate uses are annotated.",
    "invisible-format": "Format and filler code points that render blank "
                        "(soft hyphen, grapheme joiner, script fillers, "
                        "interlinear annotation, deprecated format controls).",
    "bidi": "Bidirectional controls. Valid in RTL scripts; the override and "
            "isolate members enable Trojan-Source reordering.",
    "variation-selector": "Variation selectors. Normally style glyphs; can "
                          "carry hidden payloads.",
    "tag": "Unicode Tags block. Invisible; used for text smuggling and prompt "
           "injection. Rare in ordinary prose.",
    "whitespace": "Nonstandard whitespace (NBSP, narrow no-break space, en "
                  "and em spaces, line and paragraph separators). Renders "
                  "like a space but differs from ASCII space; the class "
                  "behind the 2025 NNBSP fingerprint reports. Common in "
                  "typeset and word-processor text; --exclude whitespace "
                  "to skip.",
}

_SINGLE = {
    0x200B: ("ZERO WIDTH SPACE", "zero-width"),
    0x200C: ("ZERO WIDTH NON-JOINER", "zero-width"),
    0x200D: ("ZERO WIDTH JOINER", "zero-width"),
    0x2060: ("WORD JOINER", "zero-width"),
    0x2061: ("FUNCTION APPLICATION", "zero-width"),
    0x2062: ("INVISIBLE TIMES", "zero-width"),
    0x2063: ("INVISIBLE SEPARATOR", "zero-width"),
    0x2064: ("INVISIBLE PLUS", "zero-width"),
    0xFEFF: ("ZERO WIDTH NO-BREAK SPACE (BOM)", "zero-width"),
    0x00AD: ("SOFT HYPHEN", "invisible-format"),
    0x034F: ("COMBINING GRAPHEME JOINER", "invisible-format"),
    0x115F: ("HANGUL CHOSEONG FILLER", "invisible-format"),
    0x1160: ("HANGUL JUNGSEONG FILLER", "invisible-format"),
    0x17B4: ("KHMER VOWEL INHERENT AQ", "invisible-format"),
    0x17B5: ("KHMER VOWEL INHERENT AA", "invisible-format"),
    0x180E: ("MONGOLIAN VOWEL SEPARATOR", "invisible-format"),
    0x2800: ("BRAILLE PATTERN BLANK", "invisible-format"),
    0x3164: ("HANGUL FILLER", "invisible-format"),
    0xFFA0: ("HALFWIDTH HANGUL FILLER", "invisible-format"),
    0xFFF9: ("INTERLINEAR ANNOTATION ANCHOR", "invisible-format"),
    0xFFFA: ("INTERLINEAR ANNOTATION SEPARATOR", "invisible-format"),
    0xFFFB: ("INTERLINEAR ANNOTATION TERMINATOR", "invisible-format"),
    0x061C: ("ARABIC LETTER MARK", "bidi"),
    0x200E: ("LEFT-TO-RIGHT MARK", "bidi"),
    0x200F: ("RIGHT-TO-LEFT MARK", "bidi"),
    0x202A: ("LEFT-TO-RIGHT EMBEDDING", "bidi"),
    0x202B: ("RIGHT-TO-LEFT EMBEDDING", "bidi"),
    0x202C: ("POP DIRECTIONAL FORMATTING", "bidi"),
    0x202D: ("LEFT-TO-RIGHT OVERRIDE", "bidi"),
    0x202E: ("RIGHT-TO-LEFT OVERRIDE", "bidi"),
    0x2066: ("LEFT-TO-RIGHT ISOLATE", "bidi"),
    0x2067: ("RIGHT-TO-LEFT ISOLATE", "bidi"),
    0x2068: ("FIRST STRONG ISOLATE", "bidi"),
    0x2069: ("POP DIRECTIONAL ISOLATE", "bidi"),
}


_WHITESPACE = {
    0x0085: "NEXT LINE (NEL)",
    0x00A0: "NO-BREAK SPACE",
    0x1680: "OGHAM SPACE MARK",
    0x2000: "EN QUAD",
    0x2001: "EM QUAD",
    0x2002: "EN SPACE",
    0x2003: "EM SPACE",
    0x2004: "THREE-PER-EM SPACE",
    0x2005: "FOUR-PER-EM SPACE",
    0x2006: "SIX-PER-EM SPACE",
    0x2007: "FIGURE SPACE",
    0x2008: "PUNCTUATION SPACE",
    0x2009: "THIN SPACE",
    0x200A: "HAIR SPACE",
    0x2028: "LINE SEPARATOR",
    0x2029: "PARAGRAPH SEPARATOR",
    0x202F: "NARROW NO-BREAK SPACE",
    0x205F: "MEDIUM MATHEMATICAL SPACE",
    0x3000: "IDEOGRAPHIC SPACE",
}

# Stripping a space-like character must not weld two words together, so the
# whitespace category is normalized on strip, not deleted: space variants
# become an ASCII space, line boundaries become a newline. Everything else
# tracked by markcheck occupies no width and is deleted outright.
_STRIP_REPLACEMENT = {cp: " " for cp in _WHITESPACE}
_STRIP_REPLACEMENT[0x0085] = "\n"
_STRIP_REPLACEMENT[0x2028] = "\n"
_STRIP_REPLACEMENT[0x2029] = "\n"


# Deprecated format controls U+206A..U+206F.
def _register_deprecated_format():
    for cp in range(0x206A, 0x2070):
        _SINGLE[cp] = (unicodedata.name(chr(cp), "DEPRECATED FORMAT"),
                       "invisible-format")


_register_deprecated_format()

_PICTO_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF),
                 (0x1F1E6, 0x1F1FF), (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F))


def classify(cp):
    """Return (name, category) for a tracked code point, else None."""
    hit = _SINGLE.get(cp)
    if hit is not None:
        return hit
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF \
            or 0x180B <= cp <= 0x180D:
        return (unicodedata.name(chr(cp), "VARIATION SELECTOR"),
                "variation-selector")
    if cp == 0xE0001 or 0xE0020 <= cp <= 0xE007F:
        return (unicodedata.name(chr(cp), "TAG CHARACTER"), "tag")
    name = _WHITESPACE.get(cp)
    if name is not None:
        return (name, "whitespace")
    return None


def _pictographic(cp):
    return any(lo <= cp <= hi for lo, hi in _PICTO_RANGES)


def _note(text, i, cp):
    if i == 0 and cp == 0xFEFF:
        return "BOM at file start (conventional)"
    if cp == 0x200D:
        prev = ord(text[i - 1]) if i else -1
        nxt = ord(text[i + 1]) if i + 1 < len(text) else -1
        if _pictographic(prev) and _pictographic(nxt):
            return "joins two emoji (likely legitimate)"
    if cp in (0xFE0E, 0xFE0F):
        prev = ord(text[i - 1]) if i else -1
        if _pictographic(prev):
            return "emoji presentation selector (likely legitimate)"
    if cp in (0x00A0, 0x202F):
        prev = text[i - 1] if i else ""
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if nxt in ":;!?\u00bb%" or prev == "\u00ab":
            return "French-style punctuation spacing (likely legitimate)"
        if prev.isdigit() and nxt.isdigit():
            return "digit grouping (likely legitimate)"
    return ""


def scan(text, categories, max_hits=0):
    """Scan text and return ScanResult(hits, total, capped).

    total is the true count of tracked characters in scope. When max_hits > 0
    and more are found, hits holds only the first max_hits records and capped
    is True; total still reflects the full count. This bounds memory on
    pathological input (a file that is mostly hidden characters) while keeping
    the reported count honest.
    """
    newlines = [j for j, ch in enumerate(text) if ch == "\n"]
    hits = []
    total = 0
    capped = False
    for i, ch in enumerate(text):
        info = classify(ord(ch))
        if info is None or info[1] not in categories:
            continue
        total += 1
        if max_hits and len(hits) >= max_hits:
            capped = True
            continue
        name, category = info
        line = bisect.bisect_right(newlines, i) + 1
        col = i - (newlines[line - 2] if line > 1 else -1)
        hits.append({
            "index": i, "line": line, "column": col,
            "codepoint": ord(ch), "codepoint_hex": f"U+{ord(ch):04X}",
            "name": name, "category": category,
            "note": _note(text, i, ord(ch)),
        })
    return ScanResult(hits, total, capped)


def strip_hidden(text, categories):
    """Remove tracked characters in scope; normalize, not delete, whitespace.

    Zero-width and format characters are deleted. Whitespace-category hits
    are replaced (space variants with an ASCII space, line and paragraph
    separators with a newline) so that stripping cannot join two words.
    """
    out = []
    for ch in text:
        c = classify(ord(ch))
        if c is None or c[1] not in categories:
            out.append(ch)
        else:
            out.append(_STRIP_REPLACEMENT.get(ord(ch), ""))
    return "".join(out)


class SourceError(Exception):
    """Raised when a source cannot be read or decoded as text."""


def _decode(raw, label):
    """Decode bytes as text; return (text, encoding).

    A UTF-16/UTF-32 BOM is structural: the codec consumes it. A UTF-8 BOM is
    left in place so markcheck reports it like any other zero-width character.
    Refuses to guess a legacy 8-bit codec: a wrong guess would silently mangle
    the very bytes we are inspecting, so non-Unicode input is a clear error.

    The encoding is returned so that --strip can write a cleaned file back in
    the encoding it arrived in. Re-encoding UTF-16/UTF-32 restores the BOM the
    decoder consumed, so the round trip is byte-faithful apart from the
    characters markcheck was asked to remove.
    """
    for bom, enc in ((b"\xff\xfe\x00\x00", "utf-32"),
                     (b"\x00\x00\xfe\xff", "utf-32"),
                     (b"\xff\xfe", "utf-16"),
                     (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError as exc:
                raise SourceError(f"{label}: {enc} decode failed: {exc}")
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as exc:
        raise SourceError(
            f"{label}: not valid UTF-8 (byte 0x{raw[exc.start]:02x} at "
            f"offset {exc.start}). If this is UTF-16/UTF-32, re-save it as "
            f"UTF-8; markcheck will not guess a legacy 8-bit encoding.")


def read_source(path, max_bytes=0):
    """Read a file or stdin; return (text, label, encoding). Raises
    SourceError.

    Enforces max_bytes (0 = unlimited) before reading a whole file into memory,
    so an oversized input is refused rather than exhausting RAM.
    """
    if path is None or path == "-":
        if max_bytes:
            data = sys.stdin.buffer.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise SourceError(
                    f"<stdin>: input exceeds --max-bytes ({max_bytes}); "
                    f"pass --max-bytes 0 to allow")
        else:
            data = sys.stdin.buffer.read()
        text, encoding = _decode(data, "<stdin>")
        return text, "<stdin>", encoding
    if os.path.isdir(path):
        raise SourceError(f"{path}: is a directory")
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise SourceError(f"{path}: {exc.strerror or exc}")
    if max_bytes and size > max_bytes:
        raise SourceError(f"{path}: {size} bytes exceeds --max-bytes "
                          f"({max_bytes}); pass --max-bytes 0 to allow")
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        raise SourceError(f"{path}: {exc.strerror or exc}")
    text, encoding = _decode(raw, path)
    return text, path, encoding


def write_text(path, text, encoding="utf-8", preserve_mode_from=None):
    """Write text to path atomically and durably in the given encoding.

    Writes to a unique temp file in the same directory, fsyncs it, then
    os.replace()s it into place (atomic on the same filesystem). If
    preserve_mode_from is a path, the destination inherits that file's
    permission bits, so cleaning a 0600 file does not widen it to 0644.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".markcheck-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        if preserve_mode_from is not None:
            try:
                os.chmod(tmp, os.stat(preserve_mode_from).st_mode & 0o7777)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def report_text(label, text, result, show):
    hits, total = result.hits, result.total
    print(f"\nSource: {label}")
    print(f"Characters: {len(text)}")
    print(f"Hidden-character hits: {total}")
    if total == 0:
        print("  CLEAN. No tracked hidden characters.")
        print("  Note: byte inspection cannot detect statistical "
              "(token-level) watermarks.")
        return
    if result.capped:
        print(f"  (list capped at {len(hits)} to bound memory; counts and "
              f"summaries below cover those {len(hits)} of {total})")
    by_cat = Counter(h["category"] for h in hits)
    cats = ", ".join(f"{c}={n}" for c, n in by_cat.most_common())
    print("  By category: " + cats)
    print("  By character:")
    for (cp, name), n in Counter((h["codepoint"], h["name"])
                                 for h in hits).most_common():
        print(f"    U+{cp:04X}  {name:<34} x{n}")
    show = max(show, 0)
    print(f"  Locations (up to {show}):")
    for h in hits[:show]:
        tail = f"  {h['note']}" if h["note"] else ""
        print(f"    line {h['line']:>4} col {h['column']:>4}  "
              f"{h['codepoint_hex']} {h['name']}{tail}")
    if len(hits) > show:
        print(f"    ...{len(hits) - show} more (use --show N or --json)")


def _clean_path(path):
    head, tail = os.path.split(path)
    if "." in tail:
        stem, ext = tail.rsplit(".", 1)
        tail = f"{stem}.clean.{ext}"
    else:
        tail = tail + ".clean"
    return os.path.join(head, tail)


def resolve_categories(only, exclude):
    """Turn --only/--exclude strings into a validated category set."""
    def parse(s):
        return [x.strip() for x in (s or "").split(",") if x.strip()]
    only_list, exclude_list = parse(only), parse(exclude)
    for name in only_list + exclude_list:
        if name not in CATEGORIES:
            raise ValueError(name)
    base = set(only_list) if only_list else set(CATEGORIES)
    return base - set(exclude_list)


def build_parser():
    p = argparse.ArgumentParser(
        prog="markcheck",
        description="Scan text for hidden and invisible Unicode characters.",
        epilog="Does not detect statistical/token watermarks or C2PA "
               "metadata. See the module docstring.")
    p.add_argument("files", nargs="*", help="files to scan; omit for stdin")
    p.add_argument("--strip", action="store_true",
                   help="write a cleaned copy (FILE.clean.EXT) with hits "
                        "removed")
    p.add_argument("--in-place", action="store_true",
                   help="with --strip, overwrite the original (writes a .bak "
                        "backup unless --no-backup)")
    p.add_argument("--no-backup", action="store_true",
                   help="with --in-place, skip the .bak backup")
    p.add_argument("--stdout", action="store_true",
                   help="with --strip on stdin, write cleaned text to stdout")
    p.add_argument("--json", action="store_true", help="emit JSON")
    p.add_argument("--only", metavar="CATS",
                   help="comma-separated categories to scan "
                        "(e.g. zero-width,bidi)")
    p.add_argument("--exclude", metavar="CATS", default="",
                   help="comma-separated categories to skip")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                   metavar="N",
                   help=f"refuse inputs larger than N bytes "
                        f"(default {DEFAULT_MAX_BYTES}; 0 = unlimited)")
    p.add_argument("--max-hits", type=int, default=DEFAULT_MAX_HITS,
                   metavar="N",
                   help=f"cap stored hit records at N to bound memory "
                        f"(default {DEFAULT_MAX_HITS}; 0 = unlimited)")
    p.add_argument("--show", type=int, default=20, metavar="N",
                   help="max locations to list (default 20)")
    p.add_argument("--list-categories", action="store_true",
                   help="print the taxonomy and exit")
    p.add_argument("--version", action="version",
                   version=f"markcheck {__version__}")
    return p


def _do_strip(path, text, cleaned, args, changed, encoding="utf-8"):
    """Handle the write side of --strip. Returns a status line or None.

    changed counts characters removed or normalized. Whitespace hits are
    replaced rather than deleted, so the cleaned text is not always shorter;
    "changed" is the honest word for the total.
    """
    if path is None:
        if args.stdout:
            # stdout is a text stream in the terminal's encoding, so the
            # cleaned text goes out as text, not re-encoded bytes.
            sys.stdout.write(cleaned)
            return None
        print(f"  stdin: changed {changed}; use --stdout to emit the cleaned "
              f"text", file=sys.stderr)
        return None
    if args.in_place:
        # Follow a symlink to its target. Writing through os.replace() on the
        # link path would replace the link itself with a regular file and
        # leave the real document untouched.
        target = os.path.realpath(path)
        if not args.no_backup:
            backup = target + ".bak"
            if os.path.exists(backup):
                print(f"  refusing to overwrite existing backup {backup}; "
                      f"move it or pass --no-backup", file=sys.stderr)
                return None
            write_text(backup, text, encoding, preserve_mode_from=target)
        write_text(target, cleaned, encoding, preserve_mode_from=target)
        return f"  Cleaned in place: {target} (changed {changed})" + (
            "" if args.no_backup else f", backup {target}.bak")
    out = _clean_path(path)
    write_text(out, cleaned, encoding)
    return f"  Cleaned copy: {out} (changed {changed})"


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_categories:
        for name, desc in CATEGORIES.items():
            print(f"{name}\n    {desc}")
        return 0

    try:
        categories = resolve_categories(args.only, args.exclude)
    except ValueError as exc:
        print(f"error: unknown category: {exc}", file=sys.stderr)
        return 2
    if not categories:
        print("error: no categories left to scan", file=sys.stderr)
        return 2
    if args.no_backup and not args.in_place:
        print("error: --no-backup only applies with --in-place",
              file=sys.stderr)
        return 2
    if args.in_place and not args.strip:
        print("error: --in-place only applies with --strip", file=sys.stderr)
        return 2
    if args.stdout and not args.strip:
        print("error: --stdout only applies with --strip", file=sys.stderr)
        return 2
    if args.stdout and [f for f in args.files if f != "-"]:
        print("error: --stdout applies to stdin only; for files use --strip "
              "(writes FILE.clean.EXT) or --strip --in-place",
              file=sys.stderr)
        return 2
    if args.max_bytes < 0 or args.max_hits < 0:
        print("error: --max-bytes and --max-hits must be >= 0",
              file=sys.stderr)
        return 2

    if not args.files and sys.stdin.isatty():
        build_parser().print_help()
        return 2

    # Normalize "-" to None here so that read_source and _do_strip cannot
    # disagree about whether this source is stdin or a file on disk.
    sources = [None if p == "-" else p for p in args.files] or [None]
    any_hits = had_error = False
    results = []

    for path in sources:
        try:
            text, label, encoding = read_source(path, args.max_bytes)
        except SourceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            had_error = True
            continue

        result = scan(text, categories, args.max_hits)
        any_hits = any_hits or bool(result.total)
        results.append({"source": label, "encoding": encoding,
                        "characters": len(text),
                        "total_hits": result.total, "capped": result.capped,
                        "hits": result.hits})

        if not args.json:
            report_text(label, text, result, args.show)

        if args.strip:
            try:
                line = _do_strip(path, text,
                                 strip_hidden(text, categories),
                                 args, result.total, encoding)
            except OSError as exc:
                print(f"error: cannot write cleaned output for {label}: {exc}",
                      file=sys.stderr)
                had_error = True
            else:
                if line and not args.json:
                    print(line)

    if args.json:
        json.dump({"version": __version__,
                   "categories": sorted(categories), "results": results},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")

    if had_error:
        return 2
    return 1 if any_hits else 0


def cli():
    try:
        return main()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(cli())
