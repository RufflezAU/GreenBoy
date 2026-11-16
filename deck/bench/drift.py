"""The GPU results the game reads back, in a run against a reference run: whether any of them drifts.

    python3 -I drift.py <reference run> <run> [<limit>]

Both runs need RX_VK_LOG_READ_VALUES=1: the renderer then logs, at each CPU read of a small range of GPU results, the
range and the total of its words as floats. A change to how those results reach the CPU (RX_VK_READBACK_PRIVATE) must
leave them where the reference has them: the same scripted run reads the same ranges, with totals in the same range of
values. A range whose totals in <run> leave the reference's by more than <limit> times (default 4) is a drift; the exit
status is 1 if there is one. A range only one of the runs reads is counted, not compared: the game allocates some of
them anew (small slots at another address each run).
"""
import re
import statistics
import sys
from pathlib import Path

LINE = re.compile(r"read values (\d+) (0x[0-9a-f]+) \+(0x[0-9a-f]+) \|.*\| total (\S+)")


def totals(run):
    """{(address, size): [total, ...]} in read order, from a run's log"""
    out = {}
    for m in LINE.finditer(Path(run, "hookshot_log.txt").read_text(errors="replace")):
        out.setdefault((m.group(2), m.group(3)), []).append(float(m.group(4)))
    return out


def spread(values):
    """(the median, the 5th and the 95th percentile) of a series"""
    s = sorted(values)
    return statistics.median(s), s[len(s) // 20], s[-1 - len(s) // 20]


def far(a, b, limit):
    """whether b is more than limit times a, or a than b (both magnitudes; a value near 0 compares as 1e-3)"""
    a, b = max(abs(a), 1e-3), max(abs(b), 1e-3)
    return max(a, b) / min(a, b) > limit


def drifts(ref, run, limit, min_reads=5):
    """[(range, why)] for the ranges both runs read whose totals in run leave the reference's"""
    out = []
    for key, rv in sorted(ref.items()):
        if len(rv) < min_reads or key not in run:
            continue   # (a slot of a ring read once, or a range at another address in this run: nothing to compare)
        (rm, _, rhi), (m, _, hi) = spread(rv), spread(run[key])
        if far(rm, m, limit):
            out.append((key, f"median {m:.4g} against {rm:.4g}"))
        elif far(rhi, hi, limit):
            out.append((key, f"95th percentile {hi:.4g} against {rhi:.4g}"))
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    limit = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
    ref, run = totals(sys.argv[1]), totals(sys.argv[2])
    if not ref:
        raise SystemExit(f"{sys.argv[1]}: no 'read values' lines (RX_VK_LOG_READ_VALUES=1)")
    found = drifts(ref, run, limit)
    only = sorted(set(ref) ^ set(run))
    print(f"{len(ref)} ranges read in the reference, {len(run)} in this run, {len(only)} of them in one run only "
          f"(not compared); {len(found)} drift")
    for (addr, size), why in found:
        print(f"  {addr} +{size}: {why}")
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
