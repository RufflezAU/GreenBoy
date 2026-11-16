#!/usr/bin/env python3
"""A sampled run (run.py --sample) as folded stacks for a flame graph ("root;...;leaf count", Brendan Gregg's
flamegraph.pl or speedscope.app read it): each stack root first, under its thread's name (numbered threads merged:
ModuleSystemWorker3 -> ModuleSystemWorkerN).

    RX_MAPS=<variant>/bin python3 -I fold.py <run folder>/all.txt [thread regex] > run.folded
    flamegraph.pl run.folded > run.svg
"""
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frames  # noqa: E402
import symbols  # noqa: E402


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    want = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
    counts = collections.Counter()
    for _, thread, stack in frames.sample_times(sys.argv[1]):
        thread = re.sub(r"\d+$", "N", thread)
        if want and not want.search(thread):
            continue
        merged = []
        for fr in reversed([symbols.name(f) for f in stack]):
            if not merged or merged[-1] != fr:   # (recursion, or one symbol over several addresses: one frame)
                merged.append(fr)
        counts[";".join([thread] + merged)] += 1
    for stack, n in counts.most_common():
        print(f"{stack} {n}")


if __name__ == "__main__":
    main()
