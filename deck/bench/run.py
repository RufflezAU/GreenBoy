#!/usr/bin/env python3
"""One scripted benchmark run on the Deck, headless: load the bench save, turn the camera, measure.

    python3 -I run.py <variant> <run name> [--window S] [--settle S] [--env NAME=VALUE ...] [--gamemode] [--chain] [--sample]

<variant> is a folder under $GB_BENCH/variants (make-variant.sh). The run plays a copy of $GB_BENCH/user.template (a
save folder: README.md), so it never touches the player's saves. The game reads the variant's hookshot_env.txt
(given as environment: builds differ in where they look for the file) and hookshot_options.ini. Input goes through
HOS_INPUT_LIVE: the harness waits for the title, presses A to continue, waits for gameplay, settles, then holds the
right stick for the measured window.

Writes $GB_BENCH/runs/<run name>/: result.json (the numbers), presents.csv (HOS_PRESENT_TRACE), vm.csv (memory every
0.5 s on the trace's clock), hookshot_log.txt, timeline.txt; with --chain / --sample the HOS_CHAIN / HOS_SAMPLE_ALL
captures of the measured window. The last line printed is result.json without its per-report fps list.
"""
import argparse
import json
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import frames  # noqa: E402

BENCH = os.environ.get("GB_BENCH", os.path.expanduser("~/greenboy-bench"))
GPU = "/sys/class/drm/card0/device"

# The renderer's report every 5 s: "vk: 9600 presents, 18.2 fps; a frame: 2038 draws (...)"
VK_LINE = re.compile(r"vk: \d+ presents, ([0-9.]+) fps; a frame: (\d+) draws")
# (the renderer not loaded: the game runs on, drawing nothing, and never reaches the title. A renderer built from
# another source than the game's says the first; any failed start of it, the second)
NO_RENDERER = re.compile(r"^.*(?:vk: host version mismatch|rx: mkwvk_init returned NULL).*$", re.M)


def no_renderer(log):
    """The log line saying the renderer did not load, or None"""
    m = NO_RENDERER.search(log)
    return m.group(0).strip() if m else None
REPLAY = re.compile(r"a frame's replay time \(ms\): submit ([0-9.]+)")
GPU_TIME = re.compile(r"vk: GPU time ([0-9.]+) ms a frame")
TITLE_MIN_DRAWS = 10   # (the title menu with a save draws 19 a frame)
GAMEPLAY_DRAWS = 300   # (the title and menus draw under 100 a frame; Kokiri Forest over 1,000)


def read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def hwmon(name):
    hw = f"{GPU}/hwmon"
    for h in os.listdir(hw) if os.path.isdir(hw) else []:
        v = read(f"{hw}/{h}/{name}")
        if v:
            return int(v)
    return None


def power_state():
    """'AC 15W' / 'battery 15W': the supply and the APU's power cap, which set the CPU and GPU clocks together"""
    cap = hwmon("power1_cap")
    return f"{'AC' if read('/sys/class/power_supply/ACAD/online') == '1' else 'battery'} " + \
           (f"{cap // 1000000}W" if cap else "?")


def apu_watts():
    """The APU's average package power (CPU and GPU together), W"""
    v = hwmon("power1_average")
    return v / 1e6 if v else None


def cpu_mhz():
    """The logical processors' mean current clock, MHz"""
    v = [int(f) / 1000 for f in (read(f"/sys/devices/system/cpu/cpu{c}/cpufreq/scaling_cur_freq")
                                 for c in range(os.cpu_count() or 0)) if f]
    return statistics.mean(v) if v else None


def cpu_policy():
    base = "/sys/devices/system/cpu/cpu0/cpufreq"
    return read(f"{base}/scaling_governor") + "/" + read(f"{base}/energy_performance_preference")


def gpu_clock():
    for line in read(f"{GPU}/pp_dpm_sclk").splitlines():
        if line.endswith("*"):
            return line.split(":")[1].strip(" *")
    return "?"


def vm_sample():
    """(monotonic ns, pages swapped in, major faults, MemAvailable MB, swap used MB), on the present trace's clock"""
    vm = dict(line.split(" ", 1) for line in read("/proc/vmstat").splitlines())
    mem = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        mem[k] = int(v.split()[0]) if v.split() else 0
    return (time.monotonic_ns(), int(vm.get("pswpin", 0)), int(vm.get("pgmajfault", 0)),
            mem.get("MemAvailable", 0) // 1024, (mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) // 1024)


class Run:
    def __init__(self, args):
        self.args = args
        self.variant = os.path.join(BENCH, "variants", args.variant)
        self.out = os.path.join(BENCH, "runs", args.name)
        self.log_path = os.path.join(self.out, "hookshot_log.txt")   # (the game logs to stdout)
        self.live = os.path.join(self.out, "input.live")
        self.trace = os.path.join(self.out, "presents.csv")
        self.proc = None

    def log(self):
        return read(self.log_path)

    def say(self, msg):
        line = f"{time.strftime('%T')} {msg}"
        print(line, flush=True)
        with open(os.path.join(self.out, "timeline.txt"), "a") as f:
            f.write(line + "\n")

    def press(self, presses):
        with open(self.live, "a") as f:
            f.write(presses + "\n")
        self.say(f"input {presses}")

    def wait_for(self, predicate, timeout, what):
        end = time.time() + timeout
        while time.time() < end:
            if self.proc.poll() is not None:
                raise SystemExit(f"game exited ({self.proc.returncode}) while waiting for {what}")
            if line := no_renderer(self.log()):
                raise SystemExit(f"the renderer did not load: {line}")
            if predicate():
                return
            time.sleep(0.5)
        raise SystemExit(f"timed out after {timeout}s waiting for {what}")

    def vk_lines(self):
        return [(float(f), int(d)) for f, d in VK_LINE.findall(self.log())]

    def start(self):
        if not os.path.isdir(os.path.join(self.variant, "bin")):
            raise SystemExit(f"no variant {self.variant} (make-variant.sh)")
        template = os.path.join(BENCH, "user.template")
        if not os.path.isdir(template):
            raise SystemExit(f"no bench save at {template} (README.md)")
        if os.path.exists(self.out):
            shutil.rmtree(self.out)
        os.makedirs(self.out)
        user = os.path.join(self.out, "user")
        shutil.copytree(template, user, symlinks=True)
        open(self.live, "w").close()
        env = {k: os.environ[k] for k in ("HOME", "USER", "PATH", "XDG_RUNTIME_DIR", "LANG") if k in os.environ}
        env.update({"HOS_HEADLESS": "1", "HOS_AUDIO": "0", "HOOKSHOT_NO_UPDATE_CHECK": "1", "HOS_INPUT_LIVE": self.live,
                    "HOS_PRESENT_TRACE": self.trace, "HOS_FPS_LOG": "1"})
        for line in read(os.path.join(self.variant, "hookshot_env.txt")).splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, _, value = line.partition("=")
                env[name.strip()] = value.strip()
        if self.args.chain:
            env["HOS_CHAIN"] = os.path.join(self.out, "chain.txt")
            env["HOS_PROFILE"] = "5"
        if self.args.sample:
            env["HOS_SAMPLE_ALL"] = os.path.join(self.out, "all.txt")
            env["HOS_PROFILE"] = "5"
        for kv in self.args.env:
            name, _, value = kv.partition("=")
            env[name] = value
        with open(os.path.join(self.out, "env.json"), "w") as f:
            json.dump(env, f, indent=1)
        cmd = [os.path.join(self.variant, "bin", "hookshot"), "--user", user]
        if self.args.gamemode:   # (as deck/launcher.sh starts the game)
            cmd = ["gamemoderun"] + cmd
        self.proc = subprocess.Popen(cmd, cwd=self.variant, env=env, stdout=open(self.log_path, "w"),
                                     stderr=subprocess.STDOUT, start_new_session=True)
        self.say(f"started {self.args.variant} (pid {self.proc.pid})")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()

    def capture(self, on):
        """The samplers write only while their .go file exists: the measured window"""
        for key, name in (("chain", "chain.txt"), ("sample", "all.txt")):
            if getattr(self.args, key):
                go = os.path.join(self.out, name + ".go")
                if on:
                    open(go, "w").close()
                elif os.path.exists(go):
                    os.remove(go)

    def run(self):
        self.start()

        def title():   # (the same draw count three reports running: the start-up screen and the logos change)
            last = [d for _, d in self.vk_lines()[-3:]]
            return len(last) == 3 and len(set(last)) == 1 and TITLE_MIN_DRAWS <= last[0] < GAMEPLAY_DRAWS
        self.wait_for(title, 180, "the title")
        self.say("title")
        for _ in range(3):   # (Continue is the first entry when a save exists; A loads the newest save)
            self.press("0:A")
            time.sleep(4)
        self.wait_for(lambda: any(d >= GAMEPLAY_DRAWS for _, d in self.vk_lines()[-2:]), 120, "gameplay")
        self.say("gameplay")
        time.sleep(self.args.settle)
        # (the camera turns for the whole window, so new scenery streams in every frame)
        self.press(f"0:RRIGHT/{int((self.args.window + 10) * 1000)}")
        time.sleep(2)
        lines_before, log_before = len(self.vk_lines()), len(self.log())
        rows_before = len(read(self.trace).splitlines())
        slow = {"gpu_clocks": set(), "power": set(), "cpu_policy": set()}
        watts, mhz = [], []
        self.capture(True)
        t0 = time.time()
        vm_rows = [vm_sample()]
        next_slow = 0.0
        while time.time() - t0 < self.args.window:
            if self.proc.poll() is not None:
                raise SystemExit(f"game exited ({self.proc.returncode}) in the measured window")
            vm_rows.append(vm_sample())
            if time.time() >= next_slow:   # (the sysfs reads every 2 s)
                next_slow = time.time() + 2
                slow["gpu_clocks"].add(gpu_clock())
                slow["power"].add(power_state())
                slow["cpu_policy"].add(cpu_policy())
                watts.append(apu_watts())
                mhz.append(cpu_mhz())
            time.sleep(0.5)
        self.capture(False)
        elapsed = time.time() - t0
        with open(os.path.join(self.out, "vm.csv"), "w") as f:
            f.write("mono_ns,pswpin,pgmajfault,mem_avail_mb,swap_used_mb\n")
            f.writelines(",".join(map(str, r)) + "\n" for r in vm_rows)
        time.sleep(3 if (self.args.chain or self.args.sample) else 0)   # (the samplers close their files)
        rows_after = len(read(self.trace).splitlines())
        window_lines = self.vk_lines()[lines_before:]
        log = self.log()[log_before:]
        self.stop()

        head, rows = frames.read_trace(self.trace)
        iv = head.index("interval_ns")
        # (the trace's file lines past the header: the window's rows)
        window = rows[rows_before - 1:rows_after - 1]
        res = {"variant": self.args.variant, "run": self.args.name, "window_s": round(elapsed, 1),
               "env": self.args.env, "gamemode": self.args.gamemode,
               "trace_rows": [rows_before - 1, rows_after - 1]}
        res.update({k: sorted(v) for k, v in slow.items()})
        res.update(frames.frame_stats([r[iv] / 1e6 for r in window], elapsed))
        first, last = vm_rows[0], vm_rows[-1]
        res.update({"swap_in_mb": round((last[1] - first[1]) * 4 / 1024, 1), "major_faults": last[2] - first[2],
                    "mem_avail_mb_min": min(v[3] for v in vm_rows), "mem_avail_mb_end": last[3],
                    "swap_used_mb_end": last[4]})
        for key, values in (("apu_w_median", [w for w in watts if w is not None]),
                            ("cpu_mhz_median", [m for m in mhz if m is not None])):
            if values:
                res[key] = round(statistics.median(values), 2)
        if window_lines:
            res["log_fps"] = [f for f, _ in window_lines]
            res["draws_median"] = int(statistics.median(d for _, d in window_lines))
        for key, pattern in (("replay_ms_median", REPLAY), ("gpu_ms_median", GPU_TIME)):
            values = [float(x) for x in pattern.findall(log)]
            if values:
                res[key] = round(statistics.median(values), 2)
        with open(os.path.join(self.out, "result.json"), "w") as f:
            json.dump(res, f, indent=1)
        return res


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("variant")
    p.add_argument("name")
    p.add_argument("--window", type=float, default=60, help="seconds measured (default 60)")
    p.add_argument("--settle", type=float, default=10, help="seconds of gameplay before the camera turns (default 10)")
    p.add_argument("--env", action="append", default=[], help="NAME=VALUE over the variant's switches")
    p.add_argument("--gamemode", action="store_true", help="under gamemoderun, as deck/launcher.sh starts the game")
    p.add_argument("--chain", action="store_true", help="HOS_CHAIN over the window (scripts/chain.py)")
    p.add_argument("--sample", action="store_true", help="HOS_SAMPLE_ALL over the window (stalls.py, fold.py)")
    args = p.parse_args()
    run = Run(args)
    try:
        res = run.run()
    finally:
        run.stop()
    print(json.dumps({k: v for k, v in res.items() if k != "log_fps"}))


if __name__ == "__main__":
    sys.exit(main())
