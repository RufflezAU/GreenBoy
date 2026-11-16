# Measuring a change on the Deck

A change to the game, the renderer or a switch is measured here as an interleaved A/B: the same save, the same camera
turn, each variant in turn, several rounds, one table. Each run is headless and scripted over SSH, so it needs no
window and nobody at the Deck. A 60 s window repeats to about ±2 % fps between runs, so a difference of a few percent
needs 2-3 rounds, and stutter needs more (a long frame comes in about half the runs).

`../bench.sh` measures in a desktop session, with a window, against the emulator; this one is for comparing builds.

## Setting up (once)

1. The installed game in `~/Games/GreenBoy` (`GB_GAME` for another folder), with `configs/stable.env` and
   `configs/stable.ini`.
2. A bench folder, `~/greenboy-bench` (`GB_BENCH` for another), holding `user.template`: a copy of a save folder
   whose newest save is where you want to measure. The runs here used Kokiri Forest. Copy the game's `user` folder and
   keep the one save slot (and `option.sav`); the runs play copies of it, never the original. It is your own save, so
   it stays on your Deck, as CONTRIBUTING.md asks.
3. A variant per build to compare: `make-variant.sh <name> [<folder with hookshot and/or hookshot_vk.so>]` puts one
   in `$GB_BENCH/variants/<name>` (the installed binaries without a folder). It links the game's other files, so it
   costs only its binaries.

## Running

```sh
python3 -I ab.py <session> <rounds> base@gm exp@gm                       # two builds
python3 -I ab.py <session> <rounds> base@gm base@gm:RX_VK_PARALLEL=3      # a switch
```

`@gm` starts the variant under `gamemoderun`, as `deck/launcher.sh` does; compare like with like, since GameMode
moves the CPU's clock more than most changes move the frame rate (below). `AB_WINDOW=<s>` sets the window (default
60). A run takes about 2.5 minutes. Over SSH, start the session as a unit so it outlives the connection and the Deck
does not sleep:

```sh
systemd-run --user --unit=gb-ab --collect -p StandardOutput=file:$HOME/ab.out \
    systemd-inhibit --what=sleep:idle --why=benchmark python3 -I $PWD/ab.py s1 3 base@gm exp@gm
```

`run.py <variant> <name>` is one run (the same switches: `--env`, `--gamemode`, `--window`), for a diagnostic switch
or a sampled run. Results are in `$GB_BENCH/runs/<name>/`: `result.json` (fps, frame times p50/p90/p99, 1 % low,
frames over 100 and 250 ms, the worst frame, the replay and GPU time the renderer reports, APU watts, CPU clock and
policy, power supply and cap, major faults and free memory), `presents.csv`, `vm.csv` and the game's log.

Keep the Deck on its charger: a run draws about 15 W, and `power` in the results says whether it was (`AC` or
`battery`, and the APU's cap). A Steam per-game profile's GPU clock applies to these runs too; `gpu_clocks` records it.

## Reading a result

| tool | what it shows |
|---|---|
| `stalls.py <run>...` | each long frame: when, the game's side of it against the present call, and swap-ins, major faults and free memory around it |
| `run.py ... --sample`, then `threadstate.py <run> <thread regex>` | where a group of threads is in the long frames against the other frames (`RX_MAPS=<variant>/bin` names the frames) |
| `fold.py <run>/all.txt` | the sampled run as folded stacks for a flame graph (`flamegraph.pl`, or speedscope.app) |
| `run.py ... --chain`, then `scripts/chain.py` | the frame's critical path: which thread waited on which |

Sampling costs frame rate (about 19 -> 16 fps on the Deck), so take fps from runs without it and use sampled runs for
where the time goes.

## What was measured with it (Steam Deck LCD, SteamOS, 15 W, GPU at 1600 MHz; Kokiri Forest, camera turning)

- GameMode is the largest setting: 16.1 -> 19.0 fps, the CPU at 3.5 GHz instead of ~2.4 GHz. The frame is two serial
  halves, the game building it (~28 ms) and the replay of its submits (~22 ms), and both run on one thread each.
- `RX_VK_PARALLEL`: 0 -> 2 takes ~2.5 ms off the replay (18.6 -> 19.1 fps); 3 is no faster than 2.
- No change measured from `HOS_GUEST_MIN_SLEEP_US=0` under GameMode, `RX_VK_CHUNK=1000`, `RX_VK_VRAM_MB=2000`,
  `RX_VK_BATCH=0` or `RX_VK_BATCH_IDLE_MIN=1`.
- A readback of a GPU result waits ~22 ms every frame, on the critical path (`RX_VK_LOG_READBACK_WAITS=1`); without
  the wait (`RX_VK_NO_READBACK_WAIT=1`, which is not safe to ship: the exposure flashes) the scene runs at 26.1 fps.
