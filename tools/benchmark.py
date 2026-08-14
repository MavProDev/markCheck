#!/usr/bin/env python3
"""Measure markcheck's scan cost on representative and adversarial corpora.

Diagnostic, not a gate. Timing on shared CI runners is too noisy to assert on,
so this is never wired into the test matrix; it exists so the performance
claims in the README are reproducible rather than remembered, and so a change
to the scanner can be checked against something concrete.

Peak memory is measured with tracemalloc, which counts Python allocations made
during the call. It excludes the interpreter's own baseline, so the numbers
describe the scan, not the process.

Usage: python3 tools/benchmark.py [--mb N]
"""
import argparse
import os
import sys
import time
import tracemalloc

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import markcheck as m  # noqa: E402

PROSE = ("The quick brown fox jumps over the lazy dog. Pack my box with "
         "five dozen liquor jugs. How vexingly quick daft zebras jump! ")


def corpora(target_bytes):
    """Build each corpus to roughly target_bytes of UTF-8."""
    def repeat(unit, n=target_bytes):
        return unit * max(1, n // max(1, len(unit.encode("utf-8"))))

    return [
        ("ordinary prose", repeat(PROSE)),
        ("prose + sparse hits", repeat(PROSE[:-1] + "​ ")),
        ("newline-dense", repeat("a\n")),
        ("mostly hidden", repeat("​")),
        ("all whitespace variants", repeat("    ")),
        ("mixed unicode", repeat("中文 café \U0001f600 ")),
        ("bidi heavy", repeat("a‮b‬")),
    ]


def measure(fn):
    """Time and memory in separate passes.

    tracemalloc hooks every allocation and inflates wall-clock by an order of
    magnitude, so timing it would report the profiler's cost, not markcheck's.
    The work is deterministic, so running it twice is safe.
    """
    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start

    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak, result


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mb", type=float, default=2.0,
                    help="approximate corpus size in MB (default 2)")
    args = ap.parse_args()
    target = int(args.mb * 1024 * 1024)
    cats = set(m.DEFAULT_CATEGORIES)

    print(f"markcheck {m.__version__} | Python {sys.version.split()[0]} | "
          f"~{args.mb} MB per corpus")
    print(f"{'corpus':<26}{'MB':>6}{'scan s':>9}{'MB/s':>8}"
          f"{'peak MB':>10}{'xsize':>7}{'hits':>10}")
    print("-" * 76)

    for name, text in corpora(target):
        size = len(text.encode("utf-8"))
        size_mb = size / 1024 / 1024
        elapsed, peak, result = measure(lambda: m.scan(text, cats))
        print(f"{name:<26}{size_mb:>6.1f}{elapsed:>9.3f}"
              f"{size_mb / elapsed if elapsed else 0:>8.1f}"
              f"{peak / 1024 / 1024:>10.1f}{peak / size if size else 0:>7.1f}"
              f"{result.total:>10,}")

    print()
    print("xsize is peak scan allocation divided by input size. The hit list "
          "dominates it,")
    print("so --max-hits (default "
          f"{m.DEFAULT_MAX_HITS:,}) is what bounds the worst case, not the "
          "input size.")
    print("Re-run with --max-hits 0 semantics in mind: these figures use the "
          "library default")
    print("of no cap, which is the honest worst case for a full scan.")


if __name__ == "__main__":
    main()
