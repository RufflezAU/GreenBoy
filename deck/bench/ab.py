#!/usr/bin/env python3
"""Interleaved A/B benchmark on the Deck: run.py for each variant in turn, <rounds> times, then a summary table.

    python3 -I ab.py <session> <rounds> <spec> <spec> ...      (AB_WINDOW=<s>: the measured window, default 60)

A spec is <variant>[@gm][:NAME=VALUE,...]: a variant folder (make-variant.sh), @gm to start it under gamemoderun (as
deck/launcher.sh does), and switches over its own. The same variant twice with different switches is an A/B of the
switches. The order alternates every round (A B, B A, A B ...), so drift over the session (heat, the battery, caches
filling) falls on every variant alike. Results: $GB_BENCH/runs/<session>-<round>-<label>/, and the table in
$GB_BENCH/runs/<session>.summary.txt (with every run's numbers in <session>.json).
"""
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BENCH = os.environ.get("GB_BENCH", os.path.expanduser("~/greenboy-bench"))

COLUMNS = (   # (heading, result.json key)
    ("p50 ms", "frame_ms_p50"), ("p99 ms", "frame_ms_p99"), ("1% low fps", "fps_1pct_low"),
    ("frame stdev ms", "frame_ms_stdev"), ("replay ms", "replay_ms_median"), ("draws", "draws_median"),
    ("APU W", "apu_w_median"), ("CPU MHz", "cpu_mhz_median"), (">250 ms", "frames_over_250ms"),
    ("worst ms", "frame_ms_max"), ("major faults", "major_faults"), ("min avail MB", "mem_avail_mb_min"))


def parse_spec(spec):
    """(variant, under gamemoderun, [NAME=VALUE, ...], run label) of a spec"""
    variant, _, envs = spec.partition(":")
    gamemode = variant.endswith("@gm")
    label = spec.replace(":", "+").replace("=", "-").replace(",", "+")
    return variant.removesuffix("@gm"), gamemode, [kv for kv in envs.split(",") if kv], label


def summary(results, header):
    """The markdown table of a session: per spec, the median of its runs (fps with its range)"""
    lines = [header, "", "| variant | runs | fps median (min-max) | " + " | ".join(h for h, _ in COLUMNS) + " |",
             "|---" * (3 + len(COLUMNS)) + "|"]
    for spec, rs in results.items():
        if not rs:
            lines.append(f"| {spec} | 0 |" + " |" * (1 + len(COLUMNS)))
            continue

        def med(key):
            v = [r[key] for r in rs if r.get(key) is not None]
            return round(statistics.median(v), 2) if v else ""
        fps = [r["fps"] for r in rs]
        lines.append(f"| {spec} | {len(rs)} | {med('fps')} ({min(fps)}-{max(fps)}) | " +
                     " | ".join(str(med(k)) for _, k in COLUMNS) + " |")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    session, rounds, specs = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    window = os.environ.get("AB_WINDOW", "60")
    results = {spec: [] for spec in specs}
    failed = set()   # (a spec that failed once is not run again: a broken build fails every round the same way)
    for r in range(rounds):
        for spec in specs if r % 2 == 0 else list(reversed(specs)):
            if spec in failed:
                print(f"== round {r}: {spec}: skipped (failed before)", flush=True)
                continue
            variant, gamemode, envs, label = parse_spec(spec)
            cmd = [sys.executable, "-I", os.path.join(HERE, "run.py"), variant, f"{session}-{r}-{label}",
                   "--window", window] + (["--gamemode"] if gamemode else [])
            for kv in envs:
                cmd += ["--env", kv]
            print(f"== round {r}: {spec}", flush=True)
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            try:
                res = json.loads(p.stdout.strip().splitlines()[-1])
            except (IndexError, json.JSONDecodeError):
                print(f"   failed: {(p.stdout + p.stderr).strip()[-300:]}", flush=True)
                failed.add(spec)
                continue
            results[spec].append(res)
            print(f"   fps {res.get('fps')}  p50 {res.get('frame_ms_p50')} ms  p99 {res.get('frame_ms_p99')} ms  "
                  f"replay {res.get('replay_ms_median')} ms  {res.get('power')} {res.get('apu_w_median')} W  "
                  f"{res.get('cpu_mhz_median')} MHz {res.get('cpu_policy')}  >250 ms {res.get('frames_over_250ms')}  "
                  f"worst {res.get('frame_ms_max')} ms", flush=True)
    table = summary(results, f"session {session}: {rounds} rounds, {window} s windows, camera turning")
    print("\n" + table)
    with open(os.path.join(BENCH, "runs", f"{session}.summary.txt"), "w") as f:
        f.write(table + "\n")
    with open(os.path.join(BENCH, "runs", f"{session}.json"), "w") as f:
        json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
