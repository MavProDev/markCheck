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
import json
import os
import signal
import sys
import tempfile
import unicodedata
from collections import Counter, namedtuple

__version__ = "2.1.0"

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
    "default-ignorable": "OPT-IN. Every remaining Unicode "
                         "Default_Ignorable_Code_Point not covered above, "
                         "including reserved ranges. Off by default because "
                         "it is noisy; enable with "
                         "--include-default-ignorables for forensic work.",
}

# The curated, low-noise taxonomy. "default-ignorable" is deliberately not a
# member: it is opt-in, so the default scan keeps its signal-to-noise ratio.
DEFAULT_CATEGORIES = tuple(c for c in CATEGORIES if c != "default-ignorable")

# Ordered least to most alarming.
SEVERITIES = ("info", "low", "medium", "high")
_SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITIES)}

# The bidi members that reorder rendered text (Trojan-Source, CVE-2021-42574),
# as opposed to the marks, which merely set direction for a single character.
_HIGH_BIDI = (frozenset(range(0x202A, 0x202F))
              | frozenset(range(0x2066, 0x206A)))

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

# Named explicitly rather than via unicodedata.name(). U+180F was added in
# Unicode 14.0, so on a Python that bundles an older UCD (3.9 and 3.10 ship
# Unicode 13.0) the name lookup would miss and fall back to a generic label,
# making the reported name depend on the interpreter version and diverge from
# the browser build, which hardcodes these names.
_MONGOLIAN_FVS = {
    0x180B: "MONGOLIAN FREE VARIATION SELECTOR ONE",
    0x180C: "MONGOLIAN FREE VARIATION SELECTOR TWO",
    0x180D: "MONGOLIAN FREE VARIATION SELECTOR THREE",
    0x180F: "MONGOLIAN FREE VARIATION SELECTOR FOUR",
}


# Unicode Default_Ignorable_Code_Point, frozen at the version below and
# transcribed from DerivedCoreProperties.txt. Deliberately independent of the
# running interpreter's unicodedata: this table is the specification oracle the
# curated taxonomy is checked against, so it must not move when Python moves.
# Bumping it is an explicit decision, and the conformance test says what
# changed.
UNICODE_VERSION = "15.1.0"
DEFAULT_IGNORABLE = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C),
    (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F),
    (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)

# A single stable name for this category. Deriving names from unicodedata here
# would make the report depend on the interpreter's Unicode version (and drift
# from the generated browser build); the code point is always shown alongside.
_DEFAULT_IGNORABLE_NAME = "DEFAULT IGNORABLE CODE POINT"


def _default_ignorable(cp):
    return any(lo <= cp <= hi for lo, hi in DEFAULT_IGNORABLE)


def severity(cp, category, note):
    """Rate a hit: info, low, medium, or high.

    Detection is unchanged by this; severity only lets a caller filter. An
    annotated hit is informational by definition, because _note only fires on
    the conventional, likely-legitimate uses.
    """
    if note:
        return "info"
    if category == "tag" or cp in _HIGH_BIDI:
        return "high"
    if category == "whitespace":
        return "low"
    if category == "default-ignorable":
        return "low"
    return "medium"


def classify(cp):
    """Return (name, category) for a tracked code point, else None."""
    hit = _SINGLE.get(cp)
    if hit is not None:
        return hit
    # U+180E (MONGOLIAN VOWEL SEPARATOR) sits between the free variation
    # selectors but is not one; it is handled by _SINGLE above, which classify
    # checks first, so it never reaches this table.
    fvs = _MONGOLIAN_FVS.get(cp)
    if fvs is not None:
        return (fvs, "variation-selector")
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        return (unicodedata.name(chr(cp), "VARIATION SELECTOR"),
                "variation-selector")
    if cp == 0xE0001 or 0xE0020 <= cp <= 0xE007F:
        return (unicodedata.name(chr(cp), "TAG CHARACTER"), "tag")
    name = _WHITESPACE.get(cp)
    if name is not None:
        return (name, "whitespace")
    # Everything else the specification calls default-ignorable. This arm is
    # reached only when the caller put the opt-in category in scope, since the
    # default category set excludes it.
    if _default_ignorable(cp):
        return (_DEFAULT_IGNORABLE_NAME, "default-ignorable")
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
        # nxt must be non-empty: "" is a substring of every string, so an
        # unguarded membership test annotates a trailing NBSP as legitimate
        # French spacing, which is exactly where a watermark would sit.
        if (nxt and nxt in ":;!?\u00bb%") or prev == "\u00ab":
            return "French-style punctuation spacing (likely legitimate)"
        if prev.isdigit() and nxt.isdigit():
            return "digit grouping (likely legitimate)"
    return ""


def scan(text, categories, max_hits=0, min_severity="info"):
    """Scan text and return ScanResult(hits, total, capped).

    total is the true count of tracked characters in scope. When max_hits > 0
    and more are found, hits holds only the first max_hits records and capped
    is True; total still reflects the full count. This bounds memory on
    pathological input (a file that is mostly hidden characters) while keeping
    the reported count honest.

    min_severity narrows the scope: a hit rated below it is not counted, not
    stored, and not reported. Scope, not presentation, so the caller's exit
    status and any subsequent strip agree with what was shown.
    """
    threshold = _SEVERITY_RANK[min_severity]
    hits = []
    total = 0
    capped = False
    line = 1
    col = 0
    for i, ch in enumerate(text):
        col += 1
        cp = ord(ch)
        info = classify(cp)
        if info is not None and info[1] in categories:
            name, category = info
            note = _note(text, i, cp)
            level = severity(cp, category, note)
            if _SEVERITY_RANK[level] >= threshold:
                total += 1
                if max_hits and len(hits) >= max_hits:
                    capped = True
                else:
                    hits.append({
                        "index": i, "line": line, "column": col,
                        "codepoint": cp, "codepoint_hex": f"U+{cp:04X}",
                        "name": name, "category": category,
                        "severity": level, "note": note,
                    })
        if ch == "\n":
            line += 1
            col = 0
    return ScanResult(hits, total, capped)


def strip_hidden(text, categories, min_severity="info"):
    """Remove tracked characters in scope; normalize, not delete, whitespace.

    Zero-width and format characters are deleted. Whitespace-category hits
    are replaced (space variants with an ASCII space, line and paragraph
    separators with a newline) so that stripping cannot join two words.

    min_severity matches scan(): a hit rated below it is left alone, so
    --min-severity turns --strip into a conservative cleanup that removes only
    what was actually reported.
    """
    threshold = _SEVERITY_RANK[min_severity]
    out = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        c = classify(cp)
        if c is None or c[1] not in categories:
            out.append(ch)
            continue
        # Only pay for note/severity when a filter is actually in force.
        if threshold:
            level = severity(cp, c[1], _note(text, i, cp))
            if _SEVERITY_RANK[level] < threshold:
                out.append(ch)
                continue
        out.append(_STRIP_REPLACEMENT.get(cp, ""))
    return "".join(out)


class SourceError(Exception):
    """Raised when a source cannot be read or decoded as text."""


class OutputError(Exception):
    """Raised when a requested write cannot be performed.

    Distinct from OSError: it covers refusals that are policy, not I/O failure,
    such as declining to clobber an existing backup. Both map to exit code 2 so
    a script can tell the requested cleanup did not happen.
    """


def _decode(raw, label):
    """Decode bytes as text; return (text, encoding).

    A UTF-16/UTF-32 BOM is structural: the codec consumes it. A UTF-8 BOM is
    left in place so markcheck reports it like any other zero-width character.
    Refuses to guess a legacy 8-bit codec: a wrong guess would silently mangle
    the very bytes we are inspecting, so non-Unicode input is a clear error.

    The encoding is returned so that --strip can write a cleaned file back in
    the encoding it arrived in. The returned label records the exact byte order
    (utf-16-le/-be, utf-32-le/-be), not just the generic family: the generic
    codec re-encodes in the platform's native byte order, which would silently
    flip a big-endian document to little-endian on the way out. write_text
    restores the original BOM and byte order from this label, so the round trip
    is byte-faithful apart from the characters markcheck was asked to remove.
    """
    for bom, generic, precise in (
            (b"\xff\xfe\x00\x00", "utf-32", "utf-32-le"),
            (b"\x00\x00\xfe\xff", "utf-32", "utf-32-be"),
            (b"\xff\xfe", "utf-16", "utf-16-le"),
            (b"\xfe\xff", "utf-16", "utf-16-be")):
        if raw.startswith(bom):
            try:
                # Decode with the generic codec so it consumes the BOM and
                # reads byte order from it; keep the precise label for writing.
                return raw.decode(generic), precise
            except UnicodeDecodeError as exc:
                raise SourceError(f"{label}: {generic} decode failed: {exc}")
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
            if max_bytes:
                # getsize above is only a precheck: the file can grow between
                # the stat and the read, and special files (pipes, /proc) make
                # size a poor proxy for read volume. Enforce the limit at the
                # actual read boundary, matching the stdin path.
                raw = fh.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise SourceError(
                        f"{path}: input exceeds --max-bytes ({max_bytes}); "
                        f"pass --max-bytes 0 to allow")
            else:
                raw = fh.read()
    except OSError as exc:
        raise SourceError(f"{path}: {exc.strerror or exc}")
    text, encoding = _decode(raw, path)
    return text, path, encoding


_ENCODING_BOM = {
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
    "utf-32-le": b"\xff\xfe\x00\x00",
    "utf-32-be": b"\x00\x00\xfe\xff",
}


def _encode_with_bom(text, encoding):
    """Encode text, restoring the exact BOM/byte order that _decode recorded.

    The endian-specific codecs (utf-16-le, ...) do not emit a BOM, so the
    original one is prepended here. This preserves the source byte order
    exactly, unlike the generic utf-16/utf-32 codecs which write native order.
    """
    return _ENCODING_BOM.get(encoding, b"") + text.encode(encoding)


def _fsync_dir(directory):
    """Flush a directory entry so the rename survives a crash. Best effort.

    Only meaningful on POSIX: Windows cannot open a directory as a file, and
    a failure here costs durability, never correctness, so it stays quiet.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path, data, preserve_mode_from=None):
    """Write bytes to path atomically and durably.

    Writes to a unique temp file in the same directory, fsyncs it, then
    os.replace()s it into place (atomic on the same filesystem), then fsyncs
    the directory so the rename itself is durable. If preserve_mode_from is a
    path, the destination inherits that file's permission bits, so cleaning a
    0600 file does not widen it to 0644.

    Permission bits are preserved deliberately. Ownership, timestamps, ACLs,
    and extended attributes are not; see the README for that boundary.
    """
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".markcheck-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if preserve_mode_from is not None:
            try:
                os.chmod(tmp, os.stat(preserve_mode_from).st_mode & 0o7777)
            except OSError:
                pass
        os.replace(tmp, path)
        _fsync_dir(directory)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_text(path, text, encoding="utf-8", preserve_mode_from=None):
    """Write text to path atomically and durably, restoring any source BOM."""
    _atomic_write(path, _encode_with_bom(text, encoding), preserve_mode_from)


def copy_bytes(src, dst, preserve_mode_from=None, exclusive=False):
    """Copy src's raw bytes to dst atomically, so a backup is byte-for-byte.

    Re-encoding the decoded text cannot round-trip a UTF-16/UTF-32 big-endian
    document faithfully (native byte order leaks in); a raw copy makes the .bak
    an exact image of the original bytes regardless of encoding.

    With exclusive=True the destination is first reserved with an atomic
    exclusive create, so two concurrent runs cannot both conclude that no
    backup exists and then race to write one. Raises FileExistsError if the
    reservation is already taken. The reservation is released if the copy
    fails, so a retry is not blocked by a file this call created.
    """
    with open(src, "rb") as fh:
        data = fh.read()
    if not exclusive:
        _atomic_write(dst, data, preserve_mode_from)
        return
    # Reserve the name atomically, then fill it via the usual temp-and-replace
    # so the contents land atomically too.
    os.close(os.open(dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    try:
        _atomic_write(dst, data, preserve_mode_from)
    except BaseException:
        try:
            os.remove(dst)
        except OSError:
            pass
        raise


def report_text(label, text, result, show, file=None):
    out = file if file is not None else sys.stdout
    hits, total = result.hits, result.total
    print(f"\nSource: {label}", file=out)
    print(f"Characters: {len(text)}", file=out)
    print(f"Hidden-character hits: {total}", file=out)
    if total == 0:
        print("  CLEAN. No tracked hidden characters.", file=out)
        print("  Note: byte inspection cannot detect statistical "
              "(token-level) watermarks.", file=out)
        return
    if result.capped:
        print(f"  (list capped at {len(hits)} to bound memory; counts and "
              f"summaries below cover those {len(hits)} of {total})", file=out)
    by_cat = Counter(h["category"] for h in hits)
    cats = ", ".join(f"{c}={n}" for c, n in by_cat.most_common())
    print("  By category: " + cats, file=out)
    by_sev = Counter(h["severity"] for h in hits)
    sevs = ", ".join(f"{s}={by_sev[s]}"
                     for s in reversed(SEVERITIES) if by_sev[s])
    print("  By severity: " + sevs, file=out)
    print("  By character:", file=out)
    for (cp, name), n in Counter((h["codepoint"], h["name"])
                                 for h in hits).most_common():
        print(f"    U+{cp:04X}  {name:<34} x{n}", file=out)
    show = max(show, 0)
    print(f"  Locations (up to {show}):", file=out)
    for h in hits[:show]:
        tail = f"  {h['note']}" if h["note"] else ""
        print(f"    line {h['line']:>4} col {h['column']:>4}  "
              f"[{h['severity']:<6}] {h['codepoint_hex']} "
              f"{h['name']}{tail}", file=out)
    if len(hits) > show:
        print(f"    ...{len(hits) - show} more (use --show N or --json)",
              file=out)


def _clean_path(path):
    head, tail = os.path.split(path)
    if "." in tail:
        stem, ext = tail.rsplit(".", 1)
        tail = f"{stem}.clean.{ext}"
    else:
        tail = tail + ".clean"
    return os.path.join(head, tail)


def resolve_categories(only, exclude, include_default_ignorables=False):
    """Turn --only/--exclude strings into a validated category set.

    The base set is the curated taxonomy; the opt-in default-ignorable category
    joins it only when asked for, or when named explicitly in --only.
    """
    def parse(s):
        return [x.strip() for x in (s or "").split(",") if x.strip()]
    only_list, exclude_list = parse(only), parse(exclude)
    for name in only_list + exclude_list:
        if name not in CATEGORIES:
            raise ValueError(name)
    base = set(only_list) if only_list else set(DEFAULT_CATEGORIES)
    if include_default_ignorables:
        base.add("default-ignorable")
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
    p.add_argument("--force", action="store_true",
                   help="with --strip, overwrite an existing FILE.clean.EXT")
    p.add_argument("--only", metavar="CATS",
                   help="comma-separated categories to scan "
                        "(e.g. zero-width,bidi)")
    p.add_argument("--exclude", metavar="CATS", default="",
                   help="comma-separated categories to skip")
    p.add_argument("--min-severity", choices=SEVERITIES, default="info",
                   metavar="LEVEL",
                   help=f"report only hits at or above LEVEL "
                        f"({', '.join(SEVERITIES)}; default info). Narrows "
                        f"scope: --strip and the exit code follow it")
    p.add_argument("--suspicious-only", action="store_true",
                   help="shorthand for --min-severity medium: drop the "
                        "annotated, likely-legitimate hits")
    p.add_argument("--include-default-ignorables", action="store_true",
                   help="also scan every remaining Unicode default-ignorable "
                        "code point (noisy; for forensic use)")
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
            # Prefer the binary layer: a Windows console defaults to a locale
            # codec such as cp1252, which cannot represent most of Unicode and
            # would raise UnicodeEncodeError on ordinary input. sys.stdout is
            # not always a real file though (redirect_stdout, notebooks, and
            # embedding all replace it), so fall back to a text write.
            stream = getattr(sys.stdout, "buffer", None)
            if stream is None:
                sys.stdout.write(cleaned)
            else:
                sys.stdout.flush()
                stream.write(_encode_with_bom(cleaned, encoding))
                stream.flush()
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
            # A byte-for-byte copy of the original, not a re-encode of the
            # decoded text, so the backup is a faithful image even for
            # UTF-16/UTF-32 big-endian input. exclusive=True makes the
            # "does a backup already exist" check atomic rather than a
            # check-then-write race. --force does not apply here: the one
            # backup protecting the original is worth an explicit move.
            try:
                copy_bytes(target, backup, preserve_mode_from=target,
                           exclusive=True)
            except FileExistsError:
                raise OutputError(
                    f"refusing to overwrite existing backup {backup}; "
                    f"move it or pass --no-backup")
        write_text(target, cleaned, encoding, preserve_mode_from=target)
        return f"  Cleaned in place: {target} (changed {changed})" + (
            "" if args.no_backup else f", backup {target}.bak")
    out = _clean_path(path)
    if os.path.exists(out) and not args.force:
        raise OutputError(f"{out} already exists; pass --force to overwrite")
    write_text(out, cleaned, encoding)
    return f"  Cleaned copy: {out} (changed {changed})"


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_categories:
        for name, desc in CATEGORIES.items():
            print(f"{name}\n    {desc}")
        return 0

    try:
        categories = resolve_categories(args.only, args.exclude,
                                        args.include_default_ignorables)
    except ValueError as exc:
        print(f"error: unknown category: {exc}", file=sys.stderr)
        return 2
    if not categories:
        print("error: no categories left to scan", file=sys.stderr)
        return 2
    min_severity = ("medium" if args.suspicious_only else args.min_severity)
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
    if args.json and args.stdout:
        # Both want to own stdout: --stdout emits the cleaned document, --json
        # emits a structured report. Interleaving them yields a stream that is
        # neither valid JSON nor a clean document.
        print("error: --json and --stdout are mutually exclusive",
              file=sys.stderr)
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
    if args.force and not args.strip:
        print("error: --force only applies with --strip", file=sys.stderr)
        return 2
    if args.suspicious_only and args.min_severity != "info":
        print("error: --suspicious-only and --min-severity conflict; "
              "pass one", file=sys.stderr)
        return 2
    # in-place rewrites a file on disk; there is no file behind stdin.
    if args.in_place and (not args.files or "-" in args.files):
        print("error: --in-place needs a file argument; stdin has no file to "
              "rewrite (use --stdout for a cleaned stream)", file=sys.stderr)
        return 2
    if args.files.count("-") > 1:
        print("error: stdin ('-') can only be read once", file=sys.stderr)
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

        result = scan(text, categories, args.max_hits, min_severity)
        any_hits = any_hits or bool(result.total)
        results.append({"source": label, "encoding": encoding,
                        "characters": len(text),
                        "total_hits": result.total, "capped": result.capped,
                        "hits": result.hits})

        if not args.json:
            # In --stdout mode, stdout carries the cleaned document only, so
            # the human report goes to stderr; a redirect then captures the
            # cleaned bytes exactly, with nothing else mixed in.
            report_text(label, text, result, args.show,
                        file=sys.stderr if args.stdout else sys.stdout)

        if args.strip:
            try:
                line = _do_strip(path, text,
                                 strip_hidden(text, categories,
                                              min_severity),
                                 args, result.total, encoding)
            except (OSError, OutputError) as exc:
                print(f"error: cannot write cleaned output for {label}: {exc}",
                      file=sys.stderr)
                had_error = True
            else:
                if line and not args.json:
                    print(line)

    if args.json:
        json.dump({"version": __version__,
                   "unicode_version": UNICODE_VERSION,
                   "categories": sorted(categories),
                   "min_severity": min_severity, "results": results},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")

    if had_error:
        return 2
    return 1 if any_hits else 0


def _relax_stdio_errors():
    """Never crash on a character the console encoding cannot represent.

    A Windows console commonly uses a locale codec such as cp1252. Printing a
    filename (or any text) outside that codec would raise UnicodeEncodeError
    and take down the run. Substituting an escape is the right trade for a
    reporting tool: the output degrades, the scan still completes.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass


def _default_sigpipe():
    """Die on SIGPIPE the way a Unix filter should.

    Python installs an ignore handler and surfaces a BrokenPipeError instead.
    Catching that and returning 0 was quiet but dishonest: `markcheck f | head`
    reported success even when the scan had found hidden characters. Restoring
    the default handler makes the process terminate on the signal (status 141),
    which is what every other tool in a pipeline does. No-op on Windows, which
    has no SIGPIPE.
    """
    handler = getattr(signal, "SIGPIPE", None)
    if handler is not None:
        signal.signal(handler, signal.SIG_DFL)


def cli():
    _relax_stdio_errors()
    _default_sigpipe()
    try:
        return main()
    except BrokenPipeError:
        # Reachable on Windows, and on POSIX for a pipe that reports the error
        # before the signal arrives. Exit 2: the output was truncated, so the
        # run did not do what was asked.
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(cli())
