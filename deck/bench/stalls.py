#!/usr/bin/env python3
"""The long frames of a run's measured window: when each fell, how much of it was the game's side (from the present
before returning to its own present call: building the frame and the replay its submits do) and how much the present
itself, and the memory activity around it (vm.csv: swap-ins, major faults, MemAvailable).

    python3 -I stalls.py <run folder>... [--min MS]     (default 150)
"""
import argparse
import bisect
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frames  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="+")
    p.add_argument("--min", type=float, default=150, help="ms (default 150)")
    a = p.parse_args()
    for d in a.runs:
        r = json.load(open(os.path.join(d, "result.json")))
        head, rows = frames.read_trace(os.path.join(d, "presents.csv"))
        start, end = r["trace_rows"]
        fr = frames.Frames(head, rows, max(0, start - 1), end)
        vm = []
        if os.path.exists(os.path.join(d, "vm.csv")):
            with open(os.path.join(d, "vm.csv")) as f:
                vm = [tuple(int(x) for x in line.split(",")) for line in f.read().splitlines()[1:]]
        times = [v[0] for v in vm]
        long = fr.long(a.min)
        print(f"{d}: {len(fr.spans)} frames, {len(long)} of {a.min:.0f} ms or more; "
              f"swap-in {r.get('swap_in_mb')} MB, major faults {r.get('major_faults')} in the window")
        for t0, t1, ms, renderer_ms in long:
            line = f"  {ms:7.0f} ms at +{(t0 - fr.spans[0][0]) / 1e9:5.1f} s: game side {(t1 - t0) / 1e6:7.1f} ms, " \
                   f"present {renderer_ms:5.1f} ms"
            if vm:
                i0 = max(0, bisect.bisect_right(times, t0) - 1)
                i1 = min(len(vm) - 1, bisect.bisect_left(times, t1))
                line += f"; swap-in {(vm[i1][1] - vm[i0][1]) * 4 / 1024:.1f} MB, major faults {vm[i1][2] - vm[i0][2]}, " \
                        f"available {vm[i1][3]} MB"
            print(line)


if __name__ == "__main__":
    main()
