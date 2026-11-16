"""The numbers of a benchmark run, from the game's present trace (HOS_PRESENT_TRACE): frame-time statistics, and each
frame's window on the trace's clock. No game, no Deck: tests/test_deck_bench.py runs these on made-up traces.

presents.csv has a header, then one line a present: frame, return_ns (when the game's present call returned),
interval_ns (since the present before), present_begin_ns, renderer_begin_ns, renderer_end_ns, vcore_back_ns.
"""
import bisect
import statistics


def read_trace(path):
    """(header columns, rows as lists of ints): rows that are not whole lines of numbers (the last one, written while
    the file was read) are left out"""
    with open(path) as f:
        lines = f.read().splitlines()
    head = lines[0].split(",")
    rows = []
    for line in lines[1:]:
        parts = line.split(",")
        if len(parts) == len(head) and all(p.lstrip("-").isdigit() for p in parts):
            rows.append([int(p) for p in parts])
    return head, rows


def frame_stats(intervals_ms, elapsed_s):
    """fps over the window and the frame-time spread, from the presents' intervals (ms)"""
    iv = sorted(ms for ms in intervals_ms if ms > 0)
    if not iv:
        return {}
    n = len(iv)
    slowest = iv[int(n * 0.99):]
    return {
        "presents": n,
        "fps": round(n / elapsed_s, 2),
        "frame_ms_p50": round(iv[n // 2], 2),
        "frame_ms_p90": round(iv[int(n * 0.9)], 2),
        "frame_ms_p99": round(iv[min(n - 1, int(n * 0.99))], 2),
        "fps_1pct_low": round(1000 / statistics.mean(slowest), 2) if slowest else None,
        "frame_ms_stdev": round(statistics.pstdev(iv), 2),
        "frames_over_100ms": sum(1 for ms in iv if ms > 100),
        "frames_over_250ms": sum(1 for ms in iv if ms > 250),
        "frame_ms_max": round(iv[-1], 1),
    }


class Frames:
    """Each present of rows [start, end) of a trace as a window: from the present before it returning to its own
    present call (the game's side of the frame: building it, and the replay its submits do), with its interval"""

    def __init__(self, head, rows, start=0, end=None):
        col = {k: i for i, k in enumerate(head)}
        self.spans = []   # (from ns, to ns, interval ms, renderer ms)
        prev = None
        for r in rows[start:end]:
            if prev is not None:
                self.spans.append((prev[col["return_ns"]], r[col["present_begin_ns"]], r[col["interval_ns"]] / 1e6,
                                   (r[col["renderer_end_ns"]] - r[col["renderer_begin_ns"]]) / 1e6))
            prev = r
        self.starts = [s[0] for s in self.spans]

    def long(self, min_ms):
        return [s for s in self.spans if s[2] >= min_ms]

    def at(self, ns):
        """The frame window holding the time ns, or None (between a present call and its return)"""
        i = bisect.bisect_right(self.starts, ns) - 1
        return self.spans[i] if i >= 0 and ns <= self.spans[i][1] else None


def sample_times(path):
    """(ns, thread, frames) of each sample in a HOS_SAMPLE_ALL file: a sample's time is its "# at" line when the run had
    HOS_CHAIN, otherwise the file's "# t0_ns" plus the milliseconds that start the line"""
    t0 = at = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("# t0_ns "):
                t0, at = int(line[8:]), None
                continue
            if line.startswith("# at "):
                at = int(line[5:])
                continue
            if line.startswith("#"):
                continue
            ms, _, rest = line.rstrip("\n").partition(" ")
            thread, bar, frames = rest.partition("|")
            if not bar:
                continue
            when = at if at is not None else t0 + int(ms) * 1000000 if t0 is not None and ms.isdigit() else None
            at = None
            if when is not None:
                yield when, thread.strip(), [fr for fr in frames.split(";") if fr]
