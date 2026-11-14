"""The game's sleeps under a millisecond wait on the timer where the process has few cores, with guest coalescing on POSIX.

The game's idle job workers sleep 20 us and look again, thousands of times a second. host/hos_thread.c's sleep_ns answers
a sleep under a millisecond by yielding until its time, which keeps a logical processor busy for each sleeping thread
after hos_vcore_away() has already given up its virtual core. With SHORT_SLEEP_TIMER_THREADS cores or fewer (taking the
smaller of the allowed logical processors and physical_cores(), so a 4-core / 8-thread Steam Deck counts as 4 while an
unrestricted 8-core / 16-thread desktop counts as 8 and an affinity-pinned 4- or 6-thread run counts as 4 or 6), the
game's own sleeps (SleepThread) wait on the timer while the host's own short sleeps (the frame limiter, the audio
renderer) still yield and come back at their time. HOS_SHORT_SLEEP_TIMER, when set, is read by env_on's rule
(gpu/vk/compat/hookshot_env.h): on is the timer for every short sleep, off is yielding for every one.

On POSIX, Windows' ~500 us waitable-timer floor is absent, so guest timer sleeps coalesce to HOS_GUEST_MIN_SLEEP_US
(default 250 us) and leave the kernel's 50 us timer slack intact on pure guest worker threads instead of setting 1 us
timer slack across all 11 idle job workers; host sleeps keep their exact requested duration and 1 us timer slack.

The fixture runs the real code cut from host/hos_thread.c and host/posix/win32_posix.c on both the Windows (_WIN32) and
POSIX (!_WIN32) branches over stubs that count yields, timer waits, timer durations and PR_SET_TIMERSLACK calls.

python -I -B tests/test_short_sleep_timer.py [--cc gcc]
"""
import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
CORES = "static int physical_cores(void) {"
CHOICE = "enum { SHORT_SLEEP_TIMER_THREADS"
AWAY = "static void sleep_away(int64_t ns, int guest) {"
HOST = "void hos_sleep_ns(int64_t ns) { sleep_away(ns, 0); }\n"
SLEEP = "static void sleep_ns(int64_t ns, int guest) {"
GUEST = "void hos_sleep_logged(int64_t ns, uint64_t lr) {"
POSIX_TIMER = "typedef struct { HObj h; int64_t due; } HTimer;"
POSIX_SET = "BOOL SetWaitableTimerEx("


def block(source, marker):
    if marker not in source:
        raise SystemExit("FAIL: source has no '%s'" % marker.strip())
    start = source.index(marker)
    return source[start:start + re.search(r"^}", source[start:], re.M).end()]


def check(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


FIXTURE = r'''#define _CRT_SECURE_NO_WARNINGS
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "hookshot_env.h"   /* (env_value_off: the switches' one rule) */
#if FORCE_POSIX
#undef _WIN32
#elif !defined(_WIN32)
#define _WIN32 1
#endif
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); exit(1); } } while (0)
typedef void *HANDLE;
typedef const wchar_t *LPCWSTR;
typedef unsigned long DWORD, ULONG;
typedef uintptr_t DWORD_PTR;
typedef long LONG;
typedef int BOOL;
typedef union { int64_t QuadPart; } LARGE_INTEGER;
typedef int SRWLOCK;
#define TRUE 1
#define FALSE 0
#define SRWLOCK_INIT 0
#define INFINITE 0xFFFFFFFFul
#define ERROR_INVALID_HANDLE 6L
#define ERROR_NOT_ENOUGH_MEMORY 8L
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 2
#define TIMER_ALL_ACCESS 0x1F0003
enum { RelationProcessorCore = 0 };
typedef struct { uintptr_t ProcessorMask; int Relationship; } SYSTEM_LOGICAL_PROCESSOR_INFORMATION;
static int64_t clock_ns = 1000;
static int yields, timer_waits, sleeps, logged, threads, phys_cores, groups = 1;
static int affinity_calls, topo_calls, core_yields, aways, backs;
static int64_t timer_due;
static int64_t hos_now_ns(void) { return clock_ns; }
enum { HOS_CHAIN_WAIT = 1, HOS_CHAIN_WOKE, HOS_CHAIN_SIGNAL, HOS_CHAIN_SLEEP, HOS_CHAIN_AWAKE, HOS_CHAIN_PRESENT };
#define HOS_CHAIN(kind, key) ((void)(kind), (void)(key))   /* (HOS_CHAIN off: host/hos.h) */
static BOOL SwitchToThread(void) { yields++; clock_ns += 3000; return 1; }
static void YieldProcessor(void) { clock_ns += 100; }
static void Sleep(DWORD ms) { sleeps++; clock_ns += (int64_t)ms * 1000000; }
static BOOL GetLogicalProcessorInformation(SYSTEM_LOGICAL_PROCESSOR_INFORMATION *info, DWORD *len) {
    topo_calls++;
    if (phys_cores < 0) return 0;   /* (the call failed: the cores are not known) */
    const DWORD need = (DWORD)phys_cores * (DWORD)sizeof *info;
    if (*len < need) { *len = need; return 0; }
    for (int i = 0; i < phys_cores; i++) {
        info[i].ProcessorMask = (uintptr_t)1 << (i % (int)(sizeof(uintptr_t) * 8));
        info[i].Relationship = RelationProcessorCore;
    }
    *len = need;
    return 1;
}
#if defined(_WIN32)
static int timer_creates;
static HANDLE GetCurrentProcess(void) { return (HANDLE)(uintptr_t)1; }
static unsigned short GetActiveProcessorGroupCount(void) { return (unsigned short)groups; }
static BOOL GetProcessAffinityMask(HANDLE p, DWORD_PTR *proc, DWORD_PTR *sys) {
    (void)p;
    affinity_calls++;
    if (threads < 0) return 0;   /* (the call failed: the processors are not known) */
    *proc = threads >= 64 ? ~(DWORD_PTR)0 : (((DWORD_PTR)1 << threads) - 1);
    *sys = ~(DWORD_PTR)0;
    return 1;
}
static HANDLE CreateWaitableTimerExW(void *a, LPCWSTR n, DWORD flags, DWORD access) {
    (void)a, (void)n, (void)flags, (void)access;
    timer_creates++;
    return (HANDLE)(uintptr_t)2;
}
static BOOL SetWaitableTimerEx(HANDLE t, const LARGE_INTEGER *due, LONG period, void *f, void *arg, void *ctx, ULONG tol) {
    (void)t, (void)period, (void)f, (void)arg, (void)ctx, (void)tol;
    timer_due = -due->QuadPart * 100;
    return 1;
}
static DWORD WaitForSingleObject(HANDLE h, DWORD ms) {
    (void)h, (void)ms;
    timer_waits++;
    clock_ns += timer_due + 500000;   /* (Windows' timer wakes about half a millisecond late) */
    return 0;
}
#else
static int timer_closes, slack_calls;
static unsigned long last_slack;
typedef struct { int count; } cpu_set_t;
#define CPU_ZERO(s) ((void)((s)->count = 0))
#define CPU_COUNT(s) ((s)->count)
static int sched_getaffinity(int pid, size_t size, cpu_set_t *set) {
    (void)pid, (void)size;
    affinity_calls++;
    if (threads < 0) return -1;
    set->count = threads;
    return 0;
}
enum { H_TIMER = 0x48540004, PR_SET_TIMERSLACK = 29 };
typedef struct { int type; } HObj;
static DWORD last_error;
static int is(HANDLE h, int type) { return h && ((HObj *)h)->type == type; }
static int64_t now_ns(void) { return clock_ns; }
static int prctl(int op, unsigned long arg2, unsigned long a3, unsigned long a4, unsigned long a5) {
    (void)a3, (void)a4, (void)a5;
    CHECK(op == PR_SET_TIMERSLACK);
    slack_calls++;
    last_slack = arg2;
    return 0;
}
@POSIX_TIMER@
static BOOL CloseHandle(HANDLE h) {
    CHECK(is(h, H_TIMER));
    ((HObj *)h)->type = 0;
    free(h);
    timer_closes++;
    return 1;
}
static DWORD WaitForSingleObject(HANDLE h, DWORD ms) {
    (void)ms;
    CHECK(is(h, H_TIMER));
    timer_waits++;
    timer_due = ((HTimer *)h)->due - clock_ns;
    clock_ns = ((HTimer *)h)->due + (slack_calls ? (int64_t)last_slack : 50000);
    return 0;
}
#endif
static LONG InterlockedExchange(volatile LONG *p, LONG v) { const LONG old = *p; *p = v; return old; }
static void AcquireSRWLockExclusive(SRWLOCK *l) { CHECK(!*l); *l = 1; }
static void ReleaseSRWLockExclusive(SRWLOCK *l) { CHECK(*l); *l = 0; }
static void hos_log(const char *fmt, ...) { (void)fmt; logged++; }
static void hos_vcore_yield(void) { core_yields++; }
static int hos_vcore_away(void) { aways++; return 1; }
static void hos_vcore_back(void) { backs++; }
static void sleep_ns(int64_t ns, int guest);

@CORES@
@CHOICE@
@AWAY@
@HOST@
@SLEEP@
@GUEST@

/* one sleep under a millisecond: whether it waited on the timer; never back early, and back at its time when it yields */
static int short_sleep(int guest, int64_t ns) {
    const int64_t t0 = clock_ns;
    const int waits = timer_waits, y = yields;
    if (guest) hos_sleep_logged(ns, 0x8009a478); else hos_sleep_ns(ns);
    CHECK(clock_ns - t0 >= ns);
    if (timer_waits == waits) {
        CHECK(yields > y && clock_ns - t0 < ns + 100000);
        return 0;
    }
    CHECK(timer_waits == waits + 1 && yields == y);
    return 1;
}

int main(int argc, char **argv) {
    CHECK(argc >= 3 && argc <= 6);
    threads = atoi(argv[1]);
    const int how = atoi(argv[2]);   /* 0: all yield, 1: the game's sleeps on the timer, 2: all on the timer */
    phys_cores = argc >= 4 ? atoi(argv[3]) : threads;
    if (argc >= 5) groups = atoi(argv[4]);   /* (processor groups: the mask is then one group's) */
    const int64_t want_guest_min = argc >= 6 ? atoll(argv[5]) : 250000;
    (void)want_guest_min;
    CHECK(how >= 0 && how <= 2);
    /* (the choice by itself, at its edge) */
    CHECK(hos_short_sleep_timer(NULL, SHORT_SLEEP_TIMER_THREADS) == 1);
    CHECK(hos_short_sleep_timer(NULL, SHORT_SLEEP_TIMER_THREADS + 1) == 0);
    CHECK(hos_short_sleep_timer(NULL, 1) == 1 && hos_short_sleep_timer(NULL, 0) == 0 && hos_short_sleep_timer(NULL, -1) == 0);
    CHECK(hos_short_sleep_timer("", 1) == 0 && hos_short_sleep_timer("", 64) == 0);   /* (set but empty: off, as env_on has it) */
    CHECK(hos_short_sleep_timer("1", 64) == 2 && hos_short_sleep_timer("1", 1) == 2 && hos_short_sleep_timer("0", 1) == 0);
    CHECK(hos_short_sleep_timer("on", 64) == 2 && hos_short_sleep_timer("yes", 64) == 2 && hos_short_sleep_timer("true", 1) == 2);
    CHECK(hos_short_sleep_timer("off", 1) == 0 && hos_short_sleep_timer("No", 1) == 0 && hos_short_sleep_timer(" false ", 1) == 0);
    /* guest short sleeps first: on POSIX, pure guest worker threads keep default 50 us timer slack unless min is 0 */
    for (int i = 0; i < 3; i++) {
        CHECK(short_sleep(1, 20000) == (how >= 1));
#if !defined(_WIN32)
        if (how >= 1) {
            const int64_t expect = want_guest_min > 20000 ? want_guest_min : 20000;
            CHECK(timer_due == expect);
            CHECK(slack_calls == (want_guest_min == 0 ? 1 : 0));
        }
#endif
    }
    /* then the host's own short sleeps (the frame limiter's last part), then one more of each */
    for (int i = 0; i < 2; i++) {
        CHECK(short_sleep(0, 20000) == (how == 2));
#if !defined(_WIN32)
        if (how == 2) {
            CHECK(timer_due == 20000);   /* host short sleeps are never stretched to the guest floor */
            CHECK(slack_calls == 1 && last_slack == 1000);
        }
#endif
    }
    CHECK(short_sleep(0, 999999) == (how == 2));
#if !defined(_WIN32)
    if (how == 2) CHECK(timer_due == 999900);
#endif
    CHECK(short_sleep(1, 999999) == (how >= 1));
#if !defined(_WIN32)
    if (how >= 1) CHECK(timer_due == (want_guest_min > 999900 ? want_guest_min : 999900));
#endif
    /* a millisecond or more is the timer's whoever asks */
    int waits = timer_waits, y = yields;
    hos_sleep_ns(2000000);
#if !defined(_WIN32)
    CHECK(timer_due == 2000000 && slack_calls == 1 && last_slack == 1000);
    CHECK(timer_closes == (how >= 1 && want_guest_min > 0 ? 1 : 0));
#endif
    hos_sleep_logged(1000000, 0x8009a478);
#if !defined(_WIN32)
    CHECK(timer_due == (want_guest_min > 1000000 ? want_guest_min : 1000000));
#endif
    CHECK(timer_waits == waits + 2 && yields == y && sleeps == 0);
#if defined(_WIN32)
    CHECK(timer_creates == 1);
#else
    /* even after the thread upgraded its timer for a host sleep, a guest 20 us poll still coalesces */
    CHECK(last_error == 0);
    if (how >= 1) {
        CHECK(short_sleep(1, 20000) == 1);
        CHECK(timer_due == (want_guest_min > 20000 ? want_guest_min : 20000));
    }
#endif
    /* a sleep of 0 gives the core to a waiter and the processor to another thread: no wait */
    waits = timer_waits, y = yields;
    const int a = aways;
    hos_sleep_logged(0, 0x8009a478);
    CHECK(core_yields == 1 && yields == y + 1 && timer_waits == waits && aways == a);
    CHECK(backs == aways);   /* (every sleep gave its virtual core up and took one back) */
    CHECK(affinity_calls == (groups == 1));   /* (chosen once; with several groups the mask is not asked for) */
    CHECK(topo_calls >= (groups == 1 ? 1 : 0));
    CHECK(logged == (how ? 1 : 0));   /* (the log says so once where the timer is chosen) */
    return 0;
}
'''

# logical processors (-1: not known), physical cores (-1: not known), HOS_SHORT_SLEEP_TIMER (None: not set), how short sleeps wait
CASES = [
    (1, 1, None, 1), (2, 2, None, 1), (4, 4, None, 1), (6, 6, None, 1),
    (7, 7, None, 0), (8, 8, None, 0), (12, 12, None, 0), (16, 16, None, 0), (64, 64, None, 0),
    # SMT & affinity combinations: Steam Deck 4C/8T, 6C/12T desktop, 8C/16T desktop, and 8C/16T pinned to 4/6/7 threads
    (8, 4, None, 1), (12, 6, None, 1), (16, 8, None, 0), (32, 300, None, 0),
    (4, 8, None, 1), (6, 8, None, 1), (7, 8, None, 0),
    # Fallbacks when one side is unknown (-1) or 0
    (4, -1, None, 1), (8, -1, None, 0), (-1, 4, None, 1), (-1, 8, None, 0), (-1, -1, None, 0), (0, 0, None, 0),
    # Explicit HOS_SHORT_SLEEP_TIMER overrides
    (16, 8, "1", 2), (8, 4, "1", 2), (-1, -1, "1", 2), (8, 4, "0", 0), (16, 8, "0", 0), (8, 4, "", 0), (16, 8, "", 0),
    (16, 8, "on", 2), (16, 8, "yes", 2), (16, 8, "true", 2), (8, 4, "off", 0), (8, 4, "no", 0), (8, 4, "false", 0),
    (8, 4, " 0 ", 0), (16, 8, "2", 2),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    a = p.parse_args()

    src = (ROOT / "host" / "hos_thread.c").read_text(encoding="utf-8")
    posix_src = (ROOT / "host" / "posix" / "win32_posix.c").read_text(encoding="utf-8")
    check(POSIX_TIMER in posix_src and POSIX_SET in posix_src, "host/posix/win32_posix.c has no waitable timer block")
    p_start = posix_src.index(POSIX_TIMER)
    p_set = posix_src.index(POSIX_SET, p_start)
    posix_timer = posix_src[p_start:p_set + re.search(r"^}", posix_src[p_set:], re.M).end()]

    parts = {"@CORES@": block(src, CORES), "@CHOICE@": block(src, CHOICE), "@AWAY@": block(src, AWAY),
             "@SLEEP@": block(src, SLEEP), "@GUEST@": block(src, GUEST), "@POSIX_TIMER@": posix_timer}
    check(HOST in src, "host/hos_thread.c has no '%s'" % HOST.strip())
    parts["@HOST@"] = HOST
    # (the game's sleeps reach hos_sleep_logged: nn::os::SleepThread and the kernel's)
    check("hos_sleep_logged((int64_t)ARG(0), c->x[30]);" in src, "nn::os::SleepThread no longer sleeps through hos_sleep_logged")
    check("hos_sleep_logged((int64_t)c->x[0]" in (ROOT / "host" / "hos_svc.c").read_text(encoding="utf-8"),
          "the kernel's SleepThread no longer sleeps through hos_sleep_logged")
    env = {k: v for k, v in os.environ.items() if not k.startswith("HOS_")}

    def build(tmp, name, posix=False, **changed):
        text = FIXTURE
        for key, part in parts.items():
            text = text.replace(key, changed.get(key.strip("@").lower(), part))
        c, exe = Path(tmp) / (name + ".c"), Path(tmp) / (name + ".exe")
        c.write_text(text, encoding="utf-8")
        subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                        "-DFORCE_POSIX=%d" % (1 if posix else 0), "-I", str(ROOT / "gpu" / "vk" / "compat"),
                        str(c), "-o", str(exe)], check=True)
        return exe

    def run(exe, threads, phys, asked, how, groups=1, min_us=None, want_min_ns=None):
        e = dict(env)
        if asked is not None:
            e["HOS_SHORT_SLEEP_TIMER"] = asked
        if min_us is not None:
            e["HOS_GUEST_MIN_SLEEP_US"] = min_us
        cmd = [str(exe), str(threads), str(how), str(phys), str(groups)]
        if want_min_ns is not None:
            cmd.append(str(want_min_ns))
        return subprocess.run(cmd, env=e, capture_output=True, text=True)

    def broken(tmp, name, part, old, new, case, what, posix=False):
        check(old in parts[part], "%s no longer has the line the broken variant '%s' changes" % (part, name))
        exe = build(tmp, name, posix=posix, **{part.strip("@").lower(): parts[part].replace(old, new)})
        r = run(exe, *case)
        check(r.returncode != 0 and "FAIL:" in r.stderr, what)

    with tempfile.TemporaryDirectory(prefix="short-sleep-") as tmp:
        for posix in (False, True):
            tag = "posix" if posix else "win32"
            exe = build(tmp, "fixture_" + tag, posix=posix)
            for threads, phys, asked, how in CASES:
                r = run(exe, threads, phys, asked, how)
                check(r.returncode == 0, "%s: %d logical, %d cores, HOS_SHORT_SLEEP_TIMER %r: not as in %d\n%s"
                      % (tag, threads, phys, asked, how, r.stderr))
                for other in {0, 1, 2} - {how}:   # (and the fixture tells the three apart)
                    r = run(exe, threads, phys, asked, other)
                    check(r.returncode != 0 and "FAIL:" in r.stderr,
                          "%s: (%d, %d, %r) passes as %d too: the checks prove nothing" % (tag, threads, phys, asked, other))
            if not posix:
                # more than one processor group on Windows: the mask is one group's (4 of 128 processors, say), so all yield
                for asked, how in ((None, 0), ("1", 2), ("0", 0)):
                    r = run(exe, 4, 4, asked, how, groups=2)
                    check(r.returncode == 0, "two processor groups, a mask of 4, HOS_SHORT_SLEEP_TIMER %r: not as in %d\n%s"
                          % (asked, how, r.stderr))
                r = run(exe, 4, 4, None, 1, groups=2)
                check(r.returncode != 0 and "FAIL:" in r.stderr, "one group's mask of 4 counts as the process's processors")
            else:
                # POSIX guest short-sleep coalescing overrides (HOS_GUEST_MIN_SLEEP_US)
                for min_us, want_ns in ((None, 250000), ("", 250000), ("400", 400000), ("0", 0), ("-5", 0), ("50000", 10000000)):
                    for asked, how in ((None, 1), ("1", 2)):
                        r = run(exe, 8, 4, asked, how, min_us=min_us, want_min_ns=want_ns)
                        check(r.returncode == 0, "posix HOS_GUEST_MIN_SLEEP_US=%r (asked=%r): failed\n%s"
                              % (min_us, asked, r.stderr))

        # broken variants: each must fail the case it breaks
        broken(tmp, "never", "@CHOICE@", "threads > 0 && threads <= SHORT_SLEEP_TIMER_THREADS ? 1 : 0", "threads < 0 ? 1 : 0",
               (4, 4, None, 1), "all yielding on 4 threads passes: the processors are not looked at")
        broken(tmp, "presence", "@CHOICE@", "env_value_off(asked) ? 0 : 2", "2",
               (4, 4, "0", 0), "HOS_SHORT_SLEEP_TIMER=0 read by its presence passes")
        broken(tmp, "number", "@CHOICE@", "env_value_off(asked) ? 0 : 2", "atoi(asked) != 0 ? 2 : 0",
               (16, 8, "on", 2), "HOS_SHORT_SLEEP_TIMER=on read as a number passes: not env_on's rule")
        broken(tmp, "unwired", "@GUEST@", "sleep_away(ns, 1)", "sleep_away(ns, 0)",
               (8, 4, None, 1), "the game's sleeps passed on as the host's pass on 4C/8T")
        broken(tmp, "host-too", "@SLEEP@", "short_timer < (guest ? 1 : 2)", "!short_timer && (guest || 1)",
               (8, 4, None, 1), "the host's own short sleeps on the timer pass on 4C/8T")
        broken(tmp, "one-group", "@SLEEP@", "GetActiveProcessorGroupCount() == 1 && ", "",
               (4, 4, None, 0, 2), "one group's mask taken for the process's processors passes")
        broken(tmp, "logical-only", "@SLEEP@", "const int cores = physical_cores();", "const int cores = 0;",
               (8, 4, None, 1), "counting SMT threads instead of physical cores on 4C/8T passes", posix=True)
        broken(tmp, "posix-dead", "@SLEEP@", "if (sched_getaffinity(0, sizeof set, &set) == 0) logical = CPU_COUNT(&set);", "",
               (4, 8, None, 1), "ignoring POSIX sched_getaffinity on affinity-pinned 4T/8C passes", posix=True)
        broken(tmp, "no-coalesce", "@SLEEP@", "if (wait_ns < min_ns) wait_ns = min_ns;", "",
               (8, 4, None, 1), "uncoalesced 20 us POSIX guest sleeps pass", posix=True)
        broken(tmp, "clamp-host", "@SLEEP@", "if (guest) {", "if (1) {",
               (8, 4, "1", 2), "clamping host short sleeps to the guest floor passes", posix=True)
        broken(tmp, "slack-guest", "@SLEEP@", "int hires = !guest;", "int hires = 1;",
               (8, 4, None, 1), "setting 1 us timer slack on pure guest worker threads passes", posix=True)
        edge = "enum { SHORT_SLEEP_TIMER_THREADS = 6 };"
        check(edge in parts["@CHOICE@"], "SHORT_SLEEP_TIMER_THREADS is no longer 6: the cases above name 6 and 7 cores")


if __name__ == "__main__":
    main()
