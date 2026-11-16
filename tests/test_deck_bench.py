"""The Deck benchmark's numbers (deck/bench): frame statistics, the long frames' windows on the present trace's clock,
the sampler's sample times in both of its formats, the A/B specs and summary table, and stalls.py on a made-up run.
No game and no Deck: the traces are made here.

python -I -B tests/test_deck_bench.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "deck" / "bench"
sys.path.insert(0, str(BENCH))
import ab  # noqa: E402
import frames  # noqa: E402
import run  # noqa: E402

HEAD = "frame,return_ns,interval_ns,present_begin_ns,renderer_begin_ns,renderer_end_ns,vcore_back_ns"
MS = 1000000


def trace(intervals_ms, t0=10_000 * MS):
    """A present trace whose presents come intervals_ms apart; each present call takes 2 ms"""
    lines, ret = [HEAD], t0
    for i, ms in enumerate(intervals_ms):
        ret += int(ms * MS)
        begin = ret - 2 * MS
        lines.append(f"{i + 1},{ret},{int(ms * MS)},{begin},{begin + 100},{ret - 50},{ret - 10}")
    return "\n".join(lines) + "\n"


def expect(cond, what):
    if not cond:
        raise SystemExit("deck/bench: " + what)


def check_stats():
    iv = [50.0] * 98 + [120.0, 600.0]
    s = frames.frame_stats(iv, 5.0)
    expect(s["presents"] == 100 and s["fps"] == 20.0, f"100 presents in 5 s are 20 fps: {s}")
    expect(s["frame_ms_p50"] == 50.0 and s["frame_ms_max"] == 600.0, f"p50 / max: {s}")
    expect(s["frames_over_100ms"] == 2 and s["frames_over_250ms"] == 1, f"long frame counts: {s}")
    expect(s["fps_1pct_low"] == round(1000 / 600.0, 2), f"1% low is the slowest 1% (one frame of 100): {s}")
    expect(frames.frame_stats([0, 0], 1.0) == {}, "no frames: no numbers")


def check_windows(d):
    path = d / "presents.csv"
    # (a partial last line, as a trace read while the game writes it, is left out)
    path.write_text(trace([50, 50, 400, 50]) + "5,123")
    head, rows = frames.read_trace(path)
    expect(len(rows) == 4, f"4 whole rows, the partial one left out: {len(rows)}")
    fr = frames.Frames(head, rows)
    expect(len(fr.spans) == 3, "a window per present after the first")
    long = fr.long(150)
    expect(len(long) == 1 and long[0][2] == 400.0, f"the 400 ms frame is the long one: {long}")
    t0, t1, ms, renderer_ms = long[0]
    expect(t0 == rows[1][1] and t1 == rows[2][3], "its window: the present before returning -> its own present call")
    expect(abs((t1 - t0) / MS - 398) < 1e-6, "the game side is the interval less the present call")
    expect(fr.at(t0 + MS) == long[0], "a time inside the window finds it")
    expect(fr.at(t1 + MS) is None, "a time inside the present call is no frame's game side")


def check_samples(d):
    chain = d / "chain.txt"
    chain.write_text("# t0_ns 1000\n# at 5000\n0 MainThread|a+1;b+2\n# at 7000\n0 Worker1|c+3\n")
    got = list(frames.sample_times(chain))
    expect(got == [(5000, "MainThread", ["a+1", "b+2"]), (7000, "Worker1", ["c+3"])], f"HOS_CHAIN times: {got}")
    plain = d / "all.txt"
    plain.write_text(f"# t0_ns {10 * MS}\n2 MainThread|a+1\n7 Worker 1|b+2\nnot a sample\n")
    got = list(frames.sample_times(plain))
    expect(got == [(12 * MS, "MainThread", ["a+1"]), (17 * MS, "Worker 1", ["b+2"])], f"t0 + ms times: {got}")


def check_ab():
    expect(ab.parse_spec("base@gm:RX_VK_PARALLEL=3,HOS_X=1") ==
           ("base", True, ["RX_VK_PARALLEL=3", "HOS_X=1"], "base@gm+RX_VK_PARALLEL-3+HOS_X-1"), "a spec with switches")
    expect(ab.parse_spec("exp") == ("exp", False, [], "exp"), "a bare variant")
    table = ab.summary({"a": [{"fps": 19.0, "frame_ms_p50": 50}, {"fps": 20.0, "frame_ms_p50": 52}], "b": []}, "t")
    rows = table.splitlines()
    expect(rows[4].startswith("| a | 2 | 19.5 (19.0-20.0) | 51.0 |"), f"medians and the fps range: {rows[4]}")
    expect(rows[5].count("|") == rows[2].count("|"), "a spec with no runs keeps the columns")


def check_no_renderer():
    ok = "[hos host] boot: image 96 MB\n[hos MainThread] vk: replay ready (offscreen)\n"
    expect(run.no_renderer(ok) is None, "a renderer that loaded is no failure")
    bad = ok + "vk: host version mismatch: host has 18, expected 21\n[hos MainThread] rx: mkwvk_init returned NULL: WebGPU\n"
    expect(run.no_renderer(bad) == "vk: host version mismatch: host has 18, expected 21",
           f"a renderer from another source is found by its line: {run.no_renderer(bad)}")


def check_stalls(d):
    run = d / "run"
    run.mkdir()
    (run / "presents.csv").write_text(trace([50] * 20 + [700] + [50] * 5))
    head, rows = frames.read_trace(run / "presents.csv")
    (run / "result.json").write_text(json.dumps({"trace_rows": [2, len(rows)], "swap_in_mb": 0, "major_faults": 9}))
    t = rows[0][1]
    vm = ["mono_ns,pswpin,pgmajfault,mem_avail_mb,swap_used_mb"] + \
         [f"{t + i * 500 * MS},{100 + i},{200 + 3 * i},{900 - i},1000" for i in range(6)]
    (run / "vm.csv").write_text("\n".join(vm) + "\n")
    out = subprocess.run([sys.executable, "-I", str(BENCH / "stalls.py"), str(run)], capture_output=True, text=True)
    expect(out.returncode == 0, "stalls.py failed: " + out.stderr[-800:])
    lines = [l for l in out.stdout.splitlines() if " ms at +" in l]
    expect(len(lines) == 1 and lines[0].split()[0] == "700", f"one long frame of 700 ms: {out.stdout}")
    expect("game side   698.0 ms" in lines[0] and "major faults" in lines[0], f"its split and memory: {lines[0]}")


def main():
    check_stats()
    check_ab()
    check_no_renderer()
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        check_windows(d)
        check_samples(d)
        check_stalls(d)
    print("deck/bench: ok")


if __name__ == "__main__":
    main()
