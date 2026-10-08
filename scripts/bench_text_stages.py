"""Measure the per-utterance post-processing stages, before vs after cleanup.

Covers the edits made for audit item 12: compiled correction/snippet regexes
instead of re.compile() per pair per utterance, module-level filler regex in
smart_format, and one makedirs call instead of one per history append.

The numbers are the point: run it before and after a change and compare.
"""
import sys
import time
import unittest

# Same guard as the other test modules: skip the single-instance mutex.
argv = list(sys.argv)
if "--doctor" not in argv:
    sys.argv.append("--doctor")


def _time_ms(fn, *args, repeat=200):
    best = float("inf")
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn(*args)
        best = min(best, time.perf_counter() - t0)
    return best * 1e3


def main():
    import main as m

    print("building a 34-pair correction table (as corrections-en.txt has) ...")
    pairs = []
    for i in range(34):
        pairs.append((f"misspell{i} word", f"correct{i} word"))
    compiled = m._compile_corrections(pairs)
    text = "I said misspell0 word and misspell17 word plus misspell33 word " \
           "in a sentence of about thirty words to be realistic."

    t_compile = _time_ms(m._compile_corrections, pairs, repeat=50)
    t_apply_compiled = _time_ms(m.apply_corrections, text, compiled)
    t_apply_raw = _time_ms(m.apply_corrections, text, pairs)

    print(f"\napply_corrections on a 34-pair table:")
    print(f"  compiled path (per profile) : {t_apply_compiled:.3f} ms/utterance")
    print(f"  raw-pair path (old behaviour): {t_apply_raw:.3f} ms/utterance")
    print(f"  saving                      : "
          f"{t_apply_raw - t_apply_compiled:.3f} ms/utterance")
    print(f"  (one-time compile cost       : {t_compile:.3f} ms, amortised to 0)")

    import smart_format as sf
    t_fillers = _time_ms(sf._remove_fillers, text, "en")
    print(f"\nsmart_format._remove_fillers : {t_fillers:.3f} ms/utterance")

    assert m.apply_corrections(text, compiled) == m.apply_corrections(text, pairs), \
        "compiled and raw paths disagree!"
    print("\ncompiled and raw paths produce identical text -- verified")


if __name__ == "__main__":
    main()
    sys.exit(0)
