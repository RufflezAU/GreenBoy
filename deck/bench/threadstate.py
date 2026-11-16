#!/usr/bin/env python3
"""Where threads are during a run's long frames against its other frames, from a sampled run (run.py --sample): each
sample named by its innermost frames below libc and the driver, as a share of the thread group's samples in each kind
of frame. A state far more common in the long frames is what they wait on.

    RX_MAPS=<variant>/bin python3 -I threadstate.py <run folder> <thread regex> [--min MS] [--depth N]

The sampler visits every thread in turn, so a thread gets a sample every few tens of ms: use a group of threads
("^ModuleSystemWorker") or several runs' worth of long frames before reading much into a small share.
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frames  # noqa: E402
import symbols  # noqa: E402

SKIP = ("libc", "libdrm", "libvulkan", "libm", "?")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("run")
    p.add_argument("threads", help="regex of thread names")
    p.add_argument("--min", type=float, default=150, help="a long frame, ms (default 150)")
    p.add_argument("--depth", type=int, default=4, help="frames that name a state (default 4)")
    p.add_argument("--top", type=int, default=12)
    a = p.parse_args()
    want = re.compile(a.threads)
    r = json.load(open(os.path.join(a.run, "result.json")))
    head, rows = frames.read_trace(os.path.join(a.run, "presents.csv"))
    start, end = r["trace_rows"]
    fr = frames.Frames(head, rows, max(0, start - 1), end)
    counts = {"long": collections.Counter(), "other": collections.Counter()}
    for when, thread, stack in frames.sample_times(os.path.join(a.run, "all.txt")):
        if not want.search(thread):
            continue
        span = fr.at(when)
        if span is None:
            continue
        names = [n for n in map(symbols.name, stack) if not n.startswith(SKIP)]
        key = " <- ".join(re.sub(r"\(.*", "", n)[:56] for n in names[:a.depth])
        counts["long" if span[2] >= a.min else "other"][key] += 1
    tl, to = sum(counts["long"].values()), sum(counts["other"].values())
    print(f"{a.run} /{a.threads}/: {tl} samples in frames of {a.min:.0f} ms or more, {to} in the others")
    keys = {k for k, _ in counts["long"].most_common(a.top)} | {k for k, _ in counts["other"].most_common(a.top // 2)}
    for k in sorted(keys, key=lambda k: -counts["long"][k]):
        print(f"  long {100 * counts['long'][k] / max(1, tl):5.1f}%  other {100 * counts['other'][k] / max(1, to):5.1f}%  {k}")


if __name__ == "__main__":
    main()
