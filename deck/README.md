# Steam Deck build — what is set up here and why

This folder holds the Deck-specific pieces that live beside the game, so they survive the game folder being
rebuilt. Everything in the renderer and host runtime lives in the main source tree.

## What is in here

| file | what it is |
|---|---|
| `setup-perf.sh` | one-time `sudo` setup on the Deck: adds the user to `gamemode`, configures 15 W APU-safe dynamic CPU boost (`hookshot-perf.service`), and grants zero-copy `/dev/udmabuf` access. |
| `launcher.sh` | the launcher the Steam shortcut runs. Copies the config in, sets `HOS_GUEST_MEMFD=1` only when safe and needed, sets `ulimit -c 0`, and starts `bin/hookshot` (or `./hookshot`) under `gamemoderun`. |
| `stable.env` | the environment switches (`hookshot_env.txt` in the game folder) |
| `stable.ini` | the in-game options (`hookshot_options.ini` in the game folder) |

Install: drop `launcher.sh` into the game folder and place `stable.env` and `stable.ini` at `configs/stable.env` and
`configs/stable.ini` (or point `HOS_CONFIG` at another pair), then run `sudo ./setup-perf.sh` once and log out/in.

## One-time system setup (`setup-perf.sh`)

Run once with `sudo`:

```sh
sudo ./setup-perf.sh
```

It sets up three SteamOS pieces without starving the RDNA 2 GPU under the 15 W Van Gogh APU budget:

1. **`gamemode` group membership** — lets `launcher.sh` invoke `gamemoderun` without triggering a polkit password
   prompt in Gaming Mode.
2. **Dynamic CPU boost (`hookshot-perf.service`)** — configures `scaling_governor=powersave` with
   `energy_performance_preference=balance_performance` on `amd-pstate-epp` (AMD's hardware dynamic boost mode), or
   `scaling_governor=schedutil` on `acpi-cpufreq` / passive `cpufreq`. Pinning `governor=performance` +
   `EPP=performance` across all 8 threads permanently locks the Zen 2 cores at 3.5 GHz (~10 W) and starves the RDNA 2
   GPU inside the 15 W envelope (throttling GPU clocks down to 200–1040 MHz in outdoor scenes and frame generation).
3. **Zero-copy GPU memory (`/dev/udmabuf`)** — installs `/etc/udev/rules.d/71-hookshot-udmabuf.rules` so the user can
   open `/dev/udmabuf` `O_RDWR` and share guest `memfd` pages directly with RADV as `dma-buf`s instead of re-pinning
   host-pointer imports at every submission.

## The two things that must not be lost

**`ulimit -c 0` in the launcher.** The process aborts on the heap while closing (`malloc(): unsorted double linked
list corrupted`). That is harmless on its own, but SteamOS pipes cores to a Python submitter and this process is
495 MB with ~2.5 GB mapped, so the kernel was writing a multi-GB core and the desktop was unusable for seconds
afterwards. The corruption is still there and still un-found; it is exit-only.

**The shader preparation.** Run once, and again after any change to shader-affecting settings (such as
`RX_VK_MESH_NOCULL`):

```sh
./launcher.sh --prepare-shaders
```

(Or `./bin/hookshot --prepare-shaders` / `./hookshot --prepare-shaders` directly.) It builds every program and the
pipelines the notes predict — 17,645 of them, about 35 minutes on the Deck — and writes the caches in the game folder.
Measured effect: waits for shaders or pipelines **9.4 ms a frame → 0.0**, translation over a session
**4,608 ms → 202 ms**, at no cost in steady state (21.8 vs 21.6 fps back to back).

## Settings worth knowing

- **`RX_VK_MESH_NOCULL=2c56dc1006942f74`** — disables meshlet culling only in OoT's coarse depth-grid task shader
  (`2c56dc1006942f74`, issue 817), preventing the 10 s RDNA 2 GPU hang and eliminating its dynamic-indexed depth-grid
  walk while keeping normal hardware backface culling on all draws (unlike global `RX_VK_NOCULL=1`, which forced
  `VK_CULL_MODE_NONE` on every draw and ~2x triangle rasterization/overdraw on the 15 W iGPU).
- **`RX_VK_CHECKPOINTS=0`** — keeps `VK_AMD_buffer_marker` disabled in normal play. `RX_VK_CHECKPOINTS=1` is for
  diagnosing GPU hangs only: on AMD RADV it emits two coherent host-memory writes (`TOP_OF_PIPE` + `BOTTOM_OF_PIPE`)
  before every single draw and dispatch (~5,000+ markers per frame).
- **75 % internal resolution** (`resolution=2` in the ini). The sharpness the player chose; about 2.5 fps against
  50 %.
- `RX_VK_STAGING_IDLE_S=0` and `RX_VK_STAGING_KEEP_MB=256` — keep the upload staging arenas instead of letting them
  go stale. Making one under memory pressure cost 12–25 ms and it happened 28 times a session; 1 time after.
- `RX_VK_FRAMEGEN=1` — frame generation allowed (the in-game row decides). **Unmeasured on this hardware**: it needs
  a real window, and the test harness runs offscreen, so it cannot be A/B'd from a script. Set to `0` to rule it out.
- `HOS_REALTIME_FLOOR=10` — keeps the game's time step sane below 60 fps.
- `HOS_SHORT_SLEEP_TIMER=1` and `HOS_RESERVE_CORE=0` — safe fallbacks for older binaries so sub-millisecond guest
  sleeps wait on a timer instead of busy-spinning and all 4 Zen 2 cores remain available to guest threads (current
  builds detect both automatically on Linux).

## Measuring on this device

Frame rate swings **40 %** between identical runs (12.4 vs 17.3 fps on the same config and scene) because six
emulated cores share four physical ones with the rest of the system. The **replay time** in the log is stable to
about ±8 % and is the number to compare:

```
grep "a frame's replay time" hookshot_log.txt | tail -1
```
