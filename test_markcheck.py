"""Tests for markcheck. Run: python3 -m unittest -v

Covers the pure functions, the main() entry, real subprocess CLI invocation,
encoding edge cases, --strip safety, and a randomized round-trip fuzzer.
"""
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout

import markcheck as m

ALL = set(m.CATEGORIES)


def run_cli(args, stdin_text="", cwd=None):
    """Invoke the CLI with UTF-8 bytes on every platform.

    subprocess text mode encodes using the locale codec, which on Windows is
    typically cp1252 and cannot represent a zero-width space. Passing bytes
    and decoding explicitly keeps the test meaning the same everywhere.
    """
    proc = subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=stdin_text.encode("utf-8"), capture_output=True, cwd=cwd)
    return (proc.returncode,
            proc.stdout.decode("utf-8", "replace"),
            proc.stderr.decode("utf-8", "replace"))


SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "markcheck.py")

# Every tracked code point, for fuzzing.
TRACKED = sorted(
    list(m._SINGLE)
    + list(m._WHITESPACE)
    + list(range(0x180B, 0x180E)) + [0x180F]
    + list(range(0xFE00, 0xFE10))
    + [0xE0001] + list(range(0xE0020, 0xE0080))
)


class TestClassify(unittest.TestCase):
    def test_known_singles(self):
        self.assertEqual(m.classify(0x200B),
                         ("ZERO WIDTH SPACE", "zero-width"))
        self.assertEqual(m.classify(0x202E)[1], "bidi")
        self.assertEqual(m.classify(0x00AD)[1], "invisible-format")

    def test_ranges(self):
        self.assertEqual(m.classify(0xFE0F)[1], "variation-selector")
        self.assertEqual(m.classify(0xE0041)[1], "tag")
        self.assertEqual(m.classify(0x206B)[1], "invisible-format")

    def test_ordinary_text_is_none(self):
        for ch in "The quick brown fox, 123. \n\t":
            self.assertIsNone(m.classify(ord(ch)))

    def test_every_tracked_codepoint_classifies(self):
        for cp in TRACKED:
            self.assertIsNotNone(m.classify(cp), f"U+{cp:04X} not classified")


class TestScan(unittest.TestCase):
    def test_finds_one_of_each_category(self):
        # U+2065 is a reserved default-ignorable: in scope only when the
        # opt-in category is enabled, which ALL does here.
        text = "a\u200bb\u00adc\u202ed\ufe0fe\U000e0041f\u202fg\u2065h"
        self.assertEqual({h["category"] for h in m.scan(text, ALL).hits}, ALL)

    def test_line_and_column(self):
        hit = m.scan("clean\nx\u200by", ALL).hits[0]
        self.assertEqual((hit["line"], hit["column"]), (2, 2))

    def test_column_after_astral_and_newline(self):
        # astral char is one code point; column must stay correct past a \n
        text = "hi \U0001F600\nz\u200b"
        hit = m.scan(text, ALL).hits[0]
        self.assertEqual((hit["line"], hit["column"]), (2, 2))

    def test_bom_annotation(self):
        self.assertIn("BOM", m.scan("\ufeffhi", ALL).hits[0]["note"])

    def test_emoji_joiner_annotated(self):
        text = "\U0001f468\u200d\U0001f469"
        j = [h for h in m.scan(text, ALL).hits if h["codepoint"] == 0x200D][0]
        self.assertIn("emoji", j["note"])

    def test_vs16_after_emoji_annotated(self):
        # heart + VS16 is a normal emoji; the selector must read as legitimate
        h = m.scan("\u2764\ufe0f", ALL).hits[0]
        self.assertIn("legitimate", h["note"])

    def test_vs16_without_base_not_annotated(self):
        h = m.scan("a\ufe0f", ALL).hits[0]
        self.assertEqual(h["note"], "")

    def test_category_filter(self):
        self.assertEqual(len(m.scan("a\u200bb\u202ec", {"bidi"}).hits), 1)

    def test_empty_text(self):
        self.assertEqual(m.scan("", ALL).hits, [])

    def test_crlf_line_numbers(self):
        # Windows CRLF: the \r is an ordinary char; \n drives line numbers
        hit = m.scan("a\r\nb\r\nx\u200b", ALL).hits[0]
        self.assertEqual(hit["line"], 3)


class TestWhitespace(unittest.TestCase):
    def test_nnbsp_and_nbsp_detected(self):
        hits = m.scan("a\u202fb\u00a0c", ALL).hits
        self.assertEqual([h["codepoint"] for h in hits], [0x202F, 0x00A0])
        self.assertEqual({h["category"] for h in hits}, {"whitespace"})

    def test_strip_normalizes_instead_of_deleting(self):
        # deleting an NBSP would weld the words together
        self.assertEqual(m.strip_hidden("10\u00a0km", ALL), "10 km")
        self.assertEqual(m.strip_hidden("a\u2028b", ALL), "a\nb")

    def test_zero_width_still_deleted(self):
        self.assertEqual(m.strip_hidden("a\u200bb", ALL), "ab")

    def test_french_punctuation_annotated(self):
        h = m.scan("Non\u202f!", ALL).hits[0]
        self.assertIn("legitimate", h["note"])

    def test_digit_grouping_annotated(self):
        h = m.scan("10\u00a0000", ALL).hits[0]
        self.assertIn("digit grouping", h["note"])

    def test_trailing_nbsp_is_not_called_legitimate(self):
        # regression: "" is a substring of every string, so an unguarded
        # membership test annotated a trailing NBSP as French spacing.
        # A trailing hidden space is exactly where a watermark would sit.
        for text in ("The report concludes\u202f", "value\u00a0"):
            h = m.scan(text, ALL).hits[0]
            self.assertEqual(h["note"], "", text)

    def test_bare_nnbsp_not_annotated(self):
        # the ChatGPT-report shape: NNBSP between ordinary letters
        h = m.scan("word\u202fword", ALL).hits[0]
        self.assertEqual(h["note"], "")

    def test_exclude_whitespace(self):
        cats = m.resolve_categories(None, "whitespace")
        self.assertEqual(m.scan("a\u00a0b", cats).hits, [])

    def test_mongolian_fvs_is_variation_selector(self):
        self.assertEqual(m.classify(0x180B)[1], "variation-selector")


class TestStrip(unittest.TestCase):
    def test_removes_only_in_scope(self):
        text = "a\u200bb\u202ec"
        self.assertEqual(m.strip_hidden(text, {"zero-width"}), "ab\u202ec")
        self.assertEqual(m.strip_hidden(text, ALL), "abc")


class TestDecode(unittest.TestCase):
    def test_utf8(self):
        self.assertEqual(m._decode("caf\u00e9".encode("utf-8"), "x"),
                         ("caf\u00e9", "utf-8"))

    def test_utf8_bom_preserved_and_reported(self):
        # a UTF-8 BOM stays in the text so markcheck can report it
        text, enc = m._decode("\ufeffhi".encode("utf-8"), "x")
        self.assertEqual((text, enc), ("\ufeffhi", "utf-8"))
        self.assertIn("BOM", m.scan(text, ALL).hits[0]["note"])

    def test_utf16_bom_records_exact_byte_order(self):
        # The label must record byte order, not just the family, so --strip
        # can write the file back without flipping BE to native LE.
        le = b"\xff\xfe" + "hi\u200b".encode("utf-16-le")
        be = b"\xfe\xff" + "hi\u200b".encode("utf-16-be")
        self.assertEqual(m._decode(le, "x"), ("hi\u200b", "utf-16-le"))
        self.assertEqual(m._decode(be, "x"), ("hi\u200b", "utf-16-be"))

    def test_utf32_bom_records_exact_byte_order(self):
        le = b"\xff\xfe\x00\x00" + "hi".encode("utf-32-le")
        be = b"\x00\x00\xfe\xff" + "hi".encode("utf-32-be")
        self.assertEqual(m._decode(le, "x"), ("hi", "utf-32-le"))
        self.assertEqual(m._decode(be, "x"), ("hi", "utf-32-be"))

    def test_invalid_bytes_raise_sourceerror(self):
        with self.assertRaises(m.SourceError):
            m._decode(b"caf\xe9 \xff", "x")


class TestCleanPath(unittest.TestCase):
    def test_with_ext(self):
        self.assertEqual(m._clean_path("a/b/file.md"),
                         os.path.join("a/b", "file.clean.md"))

    def test_no_ext(self):
        self.assertEqual(m._clean_path("notes"), "notes.clean")

    def test_dotted_dir_no_file_ext(self):
        # a dot in the directory must not be treated as the file extension
        self.assertEqual(m._clean_path("v1.2/notes"),
                         os.path.join("v1.2", "notes.clean"))


class TestMainInProcess(unittest.TestCase):
    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = m.main(argv)
        return code, buf.getvalue()

    def test_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "t.md")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("clean text")
            self.assertEqual(self._run([f])[0], 0)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("bad\u200btext")
            self.assertEqual(self._run([f])[0], 1)
            self.assertEqual(self._run([os.path.join(d, "nope")])[0], 2)

    def test_unknown_category(self):
        self.assertEqual(self._run(["x", "--only", "not-a-cat"])[0], 2)

    def test_empty_categories(self):
        self.assertEqual(self._run(["x", "--only", "bidi",
                                    "--exclude", "bidi"])[0], 2)

    def test_in_place_needs_strip(self):
        self.assertEqual(self._run(["x", "--in-place"])[0], 2)


class TestStripSafety(unittest.TestCase):
    def _write(self, path, text, encoding="utf-8"):
        with open(path, "w", encoding=encoding) as fh:
            fh.write(text)

    def _read(self, path, encoding="utf-8"):
        with open(path, encoding=encoding) as fh:
            return fh.read()

    def test_in_place_writes_backup(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.txt")
            self._write(f, "x\u200by")
            m.main([f, "--strip", "--in-place"])
            self.assertEqual(self._read(f), "xy")
            self.assertEqual(self._read(f + ".bak"), "x\u200by")

    def test_in_place_refuses_to_clobber_backup(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.txt")
            self._write(f, "x\u200by")
            self._write(f + ".bak", "PRECIOUS")
            with redirect_stdout(io.StringIO()):
                code = m.main([f, "--strip", "--in-place"])
            # a refused write is an error, not a silent no-op: exit code 2
            self.assertEqual(code, 2)
            # backup untouched, original NOT stripped
            self.assertEqual(self._read(f + ".bak"), "PRECIOUS")
            self.assertEqual(self._read(f), "x\u200by")

    def test_in_place_preserves_mode(self):
        if os.name != "posix":
            self.skipTest("POSIX mode bits")
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.txt")
            self._write(f, "x\u200by")
            os.chmod(f, 0o600)
            m.main([f, "--strip", "--in-place"])
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(f + ".bak").st_mode & 0o777, 0o600)

    def test_clean_copy_default(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.md")
            self._write(f, "x\u200by")
            m.main([f, "--strip"])
            self.assertEqual(self._read(os.path.join(d, "p.clean.md")), "xy")


@unittest.skipIf(os.name == "posix" and not hasattr(os, "fork"),
                 "platform cannot spawn subprocesses (e.g. iOS)")
class TestStdinDashHandling(unittest.TestCase):
    """A "-" argument means stdin everywhere, not a file named "-"."""

    def test_dash_strip_does_not_create_junk_file(self):
        # regression: _do_strip once treated "-" as a filename and wrote a
        # file literally named "-.clean" into the working directory
        with tempfile.TemporaryDirectory() as d:
            code, out, _ = run_cli(["-", "--strip", "--stdout"],
                                   "a\u200bb", cwd=d)
            self.assertEqual(os.listdir(d), [])
            self.assertIn("ab", out)

    def test_stdout_requires_strip(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["-", "--stdout"]), 2)

    def test_stdout_rejected_with_file_arguments(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["some.txt", "--strip", "--stdout"]), 2)


class TestInPlaceSymlink(unittest.TestCase):
    def test_in_place_follows_symlink(self):
        if not hasattr(os, "symlink"):
            self.skipTest("no symlink support")
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "real.txt")
            link = os.path.join(d, "link.txt")
            with open(target, "w", encoding="utf-8") as fh:
                fh.write("x\u200by")
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation not permitted")
            with redirect_stdout(io.StringIO()):
                m.main([link, "--strip", "--in-place"])
            # the link must survive and the real document must be cleaned
            self.assertTrue(os.path.islink(link))
            with open(target, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "xy")

    def test_backup_preserves_mode(self):
        if os.name != "posix":
            self.skipTest("POSIX mode bits")
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "m.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x\u200by")
            os.chmod(f, 0o644)
            with redirect_stdout(io.StringIO()):
                m.main([f, "--strip", "--in-place"])
            self.assertEqual(os.stat(f + ".bak").st_mode & 0o777, 0o644)


class TestEncodingRoundTrip(unittest.TestCase):
    def test_strip_preserves_utf16(self):
        # regression: a UTF-16 document used to come back out as UTF-8
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "doc.txt")
            with open(f, "wb") as fh:
                fh.write("hello\u200bworld".encode("utf-16"))
            with redirect_stdout(io.StringIO()):
                m.main([f, "--strip"])
            with open(os.path.join(d, "doc.clean.txt"), "rb") as fh:
                raw = fh.read()
            self.assertEqual(raw.decode("utf-16"), "helloworld")
            self.assertIn(raw[:2], (b"\xff\xfe", b"\xfe\xff"))

    def test_strip_in_place_preserves_utf16_including_backup(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "doc.txt")
            with open(f, "wb") as fh:
                fh.write("a\u200bb".encode("utf-16"))
            with redirect_stdout(io.StringIO()):
                m.main([f, "--strip", "--in-place"])
            with open(f, "rb") as fh:
                self.assertEqual(fh.read().decode("utf-16"), "ab")
            with open(f + ".bak", "rb") as fh:
                self.assertEqual(fh.read().decode("utf-16"), "a\u200bb")

    def test_utf8_still_written_as_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "doc.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("caf\u00e9\u200b")
            with redirect_stdout(io.StringIO()):
                m.main([f, "--strip"])
            with open(os.path.join(d, "doc.clean.txt"), "rb") as fh:
                self.assertEqual(fh.read(), "caf\u00e9".encode("utf-8"))

    def test_json_reports_encoding(self):
        import json
        _, out, _ = run_cli(["--json"], "a\u200bb")
        self.assertEqual(
            json.loads(out)["results"][0]["encoding"], "utf-8")


class TestStdoutSurfaces(unittest.TestCase):
    def test_strip_stdout_without_a_binary_layer(self):
        # regression: writing to sys.stdout.buffer assumed a real file object,
        # but redirect_stdout, notebooks, and embedding all replace stdout
        # with an object that has no .buffer
        class FakeStdin:
            buffer = io.BytesIO("a\u200bb".encode("utf-8"))

            def isatty(self):
                return False

        real_stdin = sys.stdin
        sys.stdin = FakeStdin()
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = m.main(["-", "--strip", "--stdout"])
        finally:
            sys.stdin = real_stdin
        self.assertEqual(code, 1)
        self.assertIn("ab", buf.getvalue())


class TestSubprocessCLI(unittest.TestCase):
    """Exercise the real `python3 markcheck.py ...` entry, argparse and all."""
    def test_version(self):
        code, out, _ = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("markcheck", out)

    def test_stdin_pipe(self):
        code, out, _ = run_cli([], "a\u200bb")
        self.assertEqual(code, 1)
        self.assertIn("hits: 1", out)

    def test_clean_stdin_exit_zero(self):
        self.assertEqual(run_cli([], "totally clean")[0], 0)

    def test_dash_reads_stdin(self):
        self.assertEqual(run_cli(["-"], "a\u200bb")[0], 1)

    def test_json_is_valid(self):
        import json
        _, out, _ = run_cli(["--json"], "a\u200bb")
        data = json.loads(out)
        self.assertEqual(data["results"][0]["hits"][0]["codepoint"], 0x200B)

    def test_stdout_strip_survives_non_ascii(self):
        # regression: cleaned text used to go through the locale text layer,
        # which raises UnicodeEncodeError on a cp1252 Windows console
        code, out, err = run_cli(["-", "--strip", "--stdout"],
                                 "caf\u00e9\u200b \u4e2d\u6587")
        self.assertNotIn("Traceback", err)
        self.assertIn("caf\u00e9", out)

    @unittest.skipUnless(os.name == "posix", "needs the coreutils `head`")
    def test_broken_pipe_no_traceback(self):
        # pipe --list-categories into a reader that closes early
        p1 = subprocess.Popen([sys.executable, SCRIPT, "--list-categories"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        head = subprocess.Popen(["head", "-1"], stdin=p1.stdout,
                                stdout=subprocess.DEVNULL)
        p1.stdout.close()
        head.wait()
        _, err = p1.communicate()
        self.assertNotIn(b"Traceback", err)


class TestFuzz(unittest.TestCase):
    def test_strip_then_scan_is_always_clean(self):
        rng = random.Random(1234)
        pool = (list("the quick brown fox 0123 \n\t.,")
                + [chr(c) for c in TRACKED])
        for _ in range(400):
            text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 60)))
            cleaned = m.strip_hidden(text, ALL)
            self.assertEqual(m.scan(cleaned, ALL).hits, [],
                             f"residual hit after strip in {text!r}")

    def test_scan_indices_in_bounds(self):
        rng = random.Random(99)
        pool = list("abc \n") + [chr(c) for c in TRACKED]
        for _ in range(400):
            text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 40)))
            for h in m.scan(text, ALL).hits:
                self.assertTrue(0 <= h["index"] < len(text))
                self.assertGreaterEqual(h["line"], 1)
                self.assertGreaterEqual(h["column"], 1)

    def test_strip_never_adds_or_reorders_visible_text(self):
        rng = random.Random(7)
        pool = list("abcDEF123 \n") + [chr(c) for c in TRACKED]
        for _ in range(400):
            text = "".join(rng.choice(pool) for _ in range(rng.randint(0, 50)))
            cleaned = m.strip_hidden(text, ALL)
            expect = "".join(
                c if m.classify(ord(c)) is None
                else m._STRIP_REPLACEMENT.get(ord(c), "")
                for c in text)
            self.assertEqual(cleaned, expect)


class TestCaps(unittest.TestCase):
    def test_hit_cap_bounds_list_but_keeps_total(self):
        text = "\u200b" * 1000
        r = m.scan(text, ALL, max_hits=10)
        self.assertEqual(len(r.hits), 10)
        self.assertEqual(r.total, 1000)
        self.assertTrue(r.capped)

    def test_no_cap_by_default(self):
        r = m.scan("\u200b" * 50, ALL, max_hits=0)
        self.assertEqual(len(r.hits), 50)
        self.assertEqual(r.total, 50)
        self.assertFalse(r.capped)

    def test_exact_cap_not_flagged(self):
        r = m.scan("\u200b" * 5, ALL, max_hits=5)
        self.assertFalse(r.capped)

    def test_max_bytes_refuses_large_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "big.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x" * 5000)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = m.main([f, "--max-bytes", "1000"])
            self.assertEqual(code, 2)

    def test_max_bytes_zero_allows(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "ok.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x" * 5000)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(m.main([f, "--max-bytes", "0"]), 0)

    def test_negative_caps_error(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["x", "--max-hits", "-1"]), 2)


@unittest.skipIf(os.name == "posix" and not hasattr(os, "fork"),
                 "platform cannot spawn subprocesses (e.g. iOS)")
class TestOutputContract(unittest.TestCase):
    """Exact output-stream contracts (audit findings F-01, F-02)."""

    def test_strip_stdout_is_data_only(self):
        # F-01: stdout must be byte-for-byte the cleaned document, with no
        # report text mixed in. assertIn is not enough; assert exact equality.
        code, out, err = run_cli(["-", "--strip", "--stdout"], "a​b")
        self.assertEqual(code, 1)
        self.assertEqual(out, "ab")
        self.assertNotIn("Source:", out)
        # the human report is still available, on stderr
        self.assertIn("Source:", err)

    def test_strip_stdout_clean_input_is_empty(self):
        code, out, _ = run_cli(["-", "--strip", "--stdout"], "clean")
        self.assertEqual(code, 0)
        self.assertEqual(out, "clean")

    def test_json_and_stdout_are_mutually_exclusive(self):
        # F-02: the combination cannot produce a coherent stream; reject it.
        code, out, err = run_cli(["-", "--strip", "--stdout", "--json"], "a​b")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("mutually exclusive", err)


class TestFvs4(unittest.TestCase):
    """F-05: U+180F MONGOLIAN FREE VARIATION SELECTOR FOUR is in scope."""

    def test_fvs4_classified_as_variation_selector(self):
        name, category = m.classify(0x180F)
        self.assertEqual(category, "variation-selector")
        self.assertEqual(name, "MONGOLIAN FREE VARIATION SELECTOR FOUR")

    def test_fvs4_detected_in_scan(self):
        hits = m.scan("a᠏b", ALL).hits
        self.assertEqual([h["codepoint"] for h in hits], [0x180F])

    def test_vowel_separator_stays_invisible_format(self):
        # U+180E sits inside the FVS range but must remain invisible-format;
        # classify checks the single-codepoint table first.
        self.assertEqual(m.classify(0x180E)[1], "invisible-format")


class TestEndiannessPreserved(unittest.TestCase):
    """F-03: --strip preserves exact byte order; backups are byte-for-byte."""

    def _strip_in_place(self, raw):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "t.txt")
            with open(f, "wb") as fh:
                fh.write(raw)
            with redirect_stdout(io.StringIO()):
                m.main([f, "--strip", "--in-place"])
            with open(f, "rb") as fh:
                cleaned = fh.read()
            with open(f + ".bak", "rb") as fh:
                backup = fh.read()
        return cleaned, backup

    def test_utf16be_byte_order_preserved(self):
        raw = b"\xfe\xff" + "a​b".encode("utf-16-be")
        cleaned, backup = self._strip_in_place(raw)
        self.assertTrue(cleaned.startswith(b"\xfe\xff"))
        self.assertEqual(cleaned, b"\xfe\xff" + "ab".encode("utf-16-be"))
        self.assertEqual(backup, raw)  # backup is byte-for-byte the original

    def test_utf16le_byte_order_preserved(self):
        raw = b"\xff\xfe" + "a​b".encode("utf-16-le")
        cleaned, backup = self._strip_in_place(raw)
        self.assertTrue(cleaned.startswith(b"\xff\xfe"))
        self.assertEqual(cleaned, b"\xff\xfe" + "ab".encode("utf-16-le"))
        self.assertEqual(backup, raw)

    def test_utf32be_byte_order_preserved(self):
        raw = b"\x00\x00\xfe\xff" + "a​b".encode("utf-32-be")
        cleaned, backup = self._strip_in_place(raw)
        self.assertTrue(cleaned.startswith(b"\x00\x00\xfe\xff"))
        self.assertEqual(backup, raw)


class TestMongolianFvsNames(unittest.TestCase):
    """P0: names must not depend on the interpreter's Unicode version.

    U+180F arrived in Unicode 14.0, so unicodedata.name() misses it on Python
    3.9/3.10 (Unicode 13.0) and would report a generic fallback there while the
    generated browser build reports the real name.
    """

    def test_all_four_selectors_named_exactly(self):
        expected = {
            0x180B: "MONGOLIAN FREE VARIATION SELECTOR ONE",
            0x180C: "MONGOLIAN FREE VARIATION SELECTOR TWO",
            0x180D: "MONGOLIAN FREE VARIATION SELECTOR THREE",
            0x180F: "MONGOLIAN FREE VARIATION SELECTOR FOUR",
        }
        for cp, name in expected.items():
            got_name, category = m.classify(cp)
            self.assertEqual(got_name, name, f"U+{cp:04X}")
            self.assertEqual(category, "variation-selector")

    def test_names_do_not_come_from_unicodedata(self):
        # Guards the fix itself: if someone reverts to unicodedata.name, this
        # still passes on a new Python but the table is what must be present.
        self.assertIn(0x180F, m._MONGOLIAN_FVS)


class TestSeverity(unittest.TestCase):
    """G-01: the suspicion model."""

    def test_annotated_hits_are_info(self):
        for text in ("﻿hi", "\U0001f468‍\U0001f469", "10 000"):
            hit = m.scan(text, ALL).hits[0]
            self.assertTrue(hit["note"], text)
            self.assertEqual(hit["severity"], "info", text)

    def test_reordering_bidi_is_high(self):
        for cp in (0x202D, 0x202E, 0x2066, 0x2069):
            hit = m.scan("a" + chr(cp) + "b", ALL).hits[0]
            self.assertEqual(hit["severity"], "high", hex(cp))

    def test_bidi_marks_are_not_high(self):
        # A plain direction mark does not reorder anything on its own.
        hit = m.scan("a‎b", ALL).hits[0]
        self.assertEqual(hit["severity"], "medium")

    def test_tag_characters_are_high(self):
        hit = m.scan("a\U000e0041b", ALL).hits[0]
        self.assertEqual(hit["severity"], "high")

    def test_unexplained_zero_width_is_medium(self):
        self.assertEqual(m.scan("a​b", ALL).hits[0]["severity"], "medium")

    def test_plain_nonstandard_space_is_low(self):
        self.assertEqual(m.scan("a b", ALL).hits[0]["severity"], "low")

    def test_min_severity_filters_scope(self):
        text = "﻿a b​c‮d"
        self.assertEqual(m.scan(text, ALL).total, 4)
        self.assertEqual(m.scan(text, ALL, 0, "low").total, 3)
        self.assertEqual(m.scan(text, ALL, 0, "medium").total, 2)
        self.assertEqual(m.scan(text, ALL, 0, "high").total, 1)

    def test_strip_respects_min_severity(self):
        # The emoji ZWJ is info, so a medium+ strip must leave it intact.
        text = "\U0001f468‍\U0001f469 and ​"
        self.assertEqual(m.strip_hidden(text, ALL, "medium"),
                         "\U0001f468‍\U0001f469 and ")
        self.assertEqual(m.strip_hidden(text, ALL),
                         "\U0001f468\U0001f469 and ")

    def test_suspicious_only_exits_clean_on_legitimate_text(self):
        code, out, _ = run_cli(["-", "--suspicious-only"],
                               "\U0001f468‍\U0001f469 café")
        self.assertEqual(code, 0)
        self.assertIn("CLEAN", out)

    def test_severity_in_json(self):
        code, out, _ = run_cli(["--json"], "a​b")
        payload = json.loads(out)
        self.assertEqual(payload["min_severity"], "info")
        self.assertEqual(payload["results"][0]["hits"][0]["severity"],
                         "medium")


class TestDefaultIgnorableOracle(unittest.TestCase):
    """F-10/G-03: an independent specification oracle for the taxonomy.

    Parity proves Python and JS agree; it cannot prove the shared taxonomy is
    complete. This checks the curated set against frozen UCD data instead, so a
    future omission like U+180F fails here rather than passing silently.
    """

    # Default-ignorable code points deliberately outside the curated
    # taxonomy: reserved ranges and specialist formats that would add noise
    # without adding signal. Reachable via --include-default-ignorables.
    EXPECTED_GAPS = (
        {0x2065}                        # reserved
        | set(range(0xFFF0, 0xFFF9))    # reserved
        | set(range(0x1BCA0, 0x1BCA4))  # shorthand format controls
        | set(range(0x1D173, 0x1D17B))  # musical beam/phrase controls
        | {0xE0000}                     # reserved
        | set(range(0xE0002, 0xE0020))  # reserved tag range
        | set(range(0xE0080, 0xE0100))  # reserved tag range
        | set(range(0xE01F0, 0xE1000))  # reserved variation-selector range
    )

    def _all_default_ignorable(self):
        for lo, hi in m.DEFAULT_IGNORABLE:
            for cp in range(lo, hi + 1):
                yield cp

    def test_ranges_are_sorted_and_disjoint(self):
        prev_hi = -1
        for lo, hi in m.DEFAULT_IGNORABLE:
            self.assertLessEqual(lo, hi)
            self.assertGreater(lo, prev_hi, f"overlap at U+{lo:04X}")
            self.assertLess(hi, 0x110000)
            prev_hi = hi

    def test_curated_taxonomy_gaps_are_exactly_as_documented(self):
        default = set(m.DEFAULT_CATEGORIES)
        gaps = set()
        for cp in self._all_default_ignorable():
            info = m.classify(cp)
            if info is None or info[1] not in default:
                gaps.add(cp)
        self.assertEqual(gaps, self.EXPECTED_GAPS)

    def test_nothing_default_ignorable_is_invisible_to_the_tool(self):
        for cp in self._all_default_ignorable():
            self.assertIsNotNone(m.classify(cp), f"U+{cp:04X}")

    def test_opt_in_category_is_off_by_default(self):
        self.assertNotIn("default-ignorable", m.DEFAULT_CATEGORIES)
        self.assertNotIn("default-ignorable",
                         m.resolve_categories(None, ""))
        self.assertIn("default-ignorable",
                      m.resolve_categories(None, "",
                                           include_default_ignorables=True))

    def test_reserved_default_ignorable_needs_the_flag(self):
        text = "a⁥b"
        self.assertEqual(m.scan(text, set(m.DEFAULT_CATEGORIES)).total, 0)
        self.assertEqual(m.scan(text, m.resolve_categories(
            None, "", include_default_ignorables=True)).total, 1)


class TestCleanOutputCollision(unittest.TestCase):
    """F-13: an existing .clean output is not silently replaced."""

    def test_refuses_then_force_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.md")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x​y")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(m.main([f, "--strip"]), 0 or 1)
            out = os.path.join(d, "p.clean.md")
            with open(out, "w", encoding="utf-8") as fh:
                fh.write("PRECIOUS")
            with redirect_stdout(io.StringIO()):
                code = m.main([f, "--strip"])
            self.assertEqual(code, 2)
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "PRECIOUS")
            with redirect_stdout(io.StringIO()):
                m.main([f, "--strip", "--force"])
            with open(out, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "xy")

    def test_force_requires_strip(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["x", "--force"]), 2)


class TestBackupReservation(unittest.TestCase):
    """F-14: the backup name is claimed atomically, not check-then-write."""

    def test_existing_backup_still_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.txt")
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("x​y")
            with open(f + ".bak", "w", encoding="utf-8") as fh:
                fh.write("PRECIOUS")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(m.main([f, "--strip", "--in-place"]), 2)
            with open(f + ".bak", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "PRECIOUS")

    def test_copy_bytes_exclusive_raises_on_existing(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "a")
            dst = os.path.join(d, "b")
            with open(src, "wb") as fh:
                fh.write(b"data")
            with open(dst, "wb") as fh:
                fh.write(b"taken")
            with self.assertRaises(FileExistsError):
                m.copy_bytes(src, dst, exclusive=True)
            with open(dst, "rb") as fh:
                self.assertEqual(fh.read(), b"taken")


class TestFlagValidation(unittest.TestCase):
    """F-17: nonsensical flag states are rejected with a clear message."""

    def test_in_place_on_stdin_rejected(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["-", "--strip", "--in-place"]), 2)
            self.assertEqual(m.main(["--strip", "--in-place"]), 2)

    def test_repeated_stdin_rejected(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["-", "-"]), 2)

    def test_conflicting_severity_flags_rejected(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(
                m.main(["-", "--suspicious-only",
                        "--min-severity", "high"]), 2)


class TestBoundedFileRead(unittest.TestCase):
    """F-07: the read is bounded even when the stat precheck is fooled."""

    def test_read_rejects_when_getsize_underreports(self):
        # Simulate a file that grew after the stat, or a special file whose
        # size metadata lies: getsize says small, the bytes are large. The
        # bounded read (max_bytes+1) must still reject.
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "grow.txt")
            with open(f, "wb") as fh:
                fh.write(b"x" * 2000)
            with unittest.mock.patch("os.path.getsize", return_value=10):
                with self.assertRaises(m.SourceError):
                    m.read_source(f, max_bytes=1000)


if __name__ == "__main__":
    unittest.main()
