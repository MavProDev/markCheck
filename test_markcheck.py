"""Tests for markcheck. Run: python3 -m unittest -v

Covers the pure functions, the main() entry, real subprocess CLI invocation,
encoding edge cases, --strip safety, and a randomized round-trip fuzzer.
"""
import io
import os
import random
import subprocess
import sys
import tempfile
import unittest
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
    + list(range(0x180B, 0x180E))
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
        text = "a\u200bb\u00adc\u202ed\ufe0fe\U000e0041f\u202fg"
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

    def test_utf16_bom(self):
        self.assertEqual(m._decode("hi\u200b".encode("utf-16"), "x"),
                         ("hi\u200b", "utf-16"))

    def test_utf32_bom(self):
        self.assertEqual(m._decode("hi".encode("utf-32"), "x"),
                         ("hi", "utf-32"))

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
            open(f, "w", encoding="utf-8").write("clean text")
            self.assertEqual(self._run([f])[0], 0)
            open(f, "w", encoding="utf-8").write("bad\u200btext")
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
    def test_in_place_writes_backup(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.txt")
            open(f, "w", encoding="utf-8").write("x\u200by")
            m.main([f, "--strip", "--in-place"])
            self.assertEqual(open(f, encoding="utf-8").read(), "xy")
            self.assertEqual(open(f + ".bak", encoding="utf-8").read(),
                             "x\u200by")

    def test_in_place_refuses_to_clobber_backup(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.txt")
            open(f, "w", encoding="utf-8").write("x\u200by")
            open(f + ".bak", "w", encoding="utf-8").write("PRECIOUS")
            m.main([f, "--strip", "--in-place"])
            # backup untouched, original NOT stripped
            self.assertEqual(open(f + ".bak", encoding="utf-8").read(),
                             "PRECIOUS")
            self.assertEqual(open(f, encoding="utf-8").read(), "x\u200by")

    def test_in_place_preserves_mode(self):
        if os.name != "posix":
            self.skipTest("POSIX mode bits")
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.txt")
            open(f, "w", encoding="utf-8").write("x\u200by")
            os.chmod(f, 0o600)
            m.main([f, "--strip", "--in-place"])
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(f + ".bak").st_mode & 0o777, 0o600)

    def test_clean_copy_default(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "p.md")
            open(f, "w", encoding="utf-8").write("x\u200by")
            m.main([f, "--strip"])
            self.assertEqual(open(os.path.join(d, "p.clean.md"),
                                  encoding="utf-8").read(), "xy")


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
            open(f, "w", encoding="utf-8").write("x" * 5000)
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = m.main([f, "--max-bytes", "1000"])
            self.assertEqual(code, 2)

    def test_max_bytes_zero_allows(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "ok.txt")
            open(f, "w", encoding="utf-8").write("x" * 5000)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(m.main([f, "--max-bytes", "0"]), 0)

    def test_negative_caps_error(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(m.main(["x", "--max-hits", "-1"]), 2)


if __name__ == "__main__":
    unittest.main()
