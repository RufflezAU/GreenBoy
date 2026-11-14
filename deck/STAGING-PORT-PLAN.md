# Porting the staging arenas onto this tree

This tree (Carbon's) is the base: measured 23.7 fps median / 22.5 p10 under a camera-spinning
harness at ~710 draws, against 22.9 / 20.8 for our tree, even though our replay median is 1.5 ms
lower. It also carries his GPU-submission behaviour, which he reports is worth more than that.

What it lacks is the texture staging, the change whose recorded effect was **camera stalls 28 → 1**.

## What to bring over

| commit | size | what |
|---|---|---|
| `2350302c` | 152 lines (`vk_memory.cpp` 150, `vk_internal.h` 1, `vk_vma.cpp` 5) | `Capture::stage` + `sidx` + `buf_cached`; `stage_get`/`stage_put`/`stage_on`; fills the stage for texture pages in `take_capture`; the shadow reads from the stage instead of the capture buffer |
| `6b2590a8` | 31 lines (`vk_replay.cpp` 5, `vk_texture.cpp` 26) | makes the arenas before the game's memory and keeps them (`RX_VK_STAGING_IDLE_S`, `RX_VK_STAGING_KEEP_MB`) |

Both are in this repository's history: `git show 2350302c -- gpu/vk/vk_memory.cpp`.

## Why it is an adaptation, not a paste

This tree's capture path is restructured: `Capture::host_buf` for a deferred texture-only capture when
`!pool_capture_on()` (no VkBuffer/VmaAllocation), `guarded_copy`, and the allocation happens at a
different place (around line 1555, `if (!c) c = std::make_unique<Capture>()`). The two
`vk_memory.cpp` files are 565 lines apart (3902 here, 4435 there).

The three conflicts a `git cherry-pick -x 2350302c` produces are exactly those places:

1. the capture allocation + `stage_put(*c)` at the end of it;
2. the capture fill: here `host_buf`/`pools` branches, there a single `cap_buf_get` path;
3. the shadow's copy source: `pairs.push_back({slot.b.get(), src + ...})` becomes the stage address
   when `sidx[slots[i]] >= 0`.

Resolve by putting the stage next to `host_buf` (same lifetime rules) and keeping this tree's
branches, rather than taking the other side wholesale.

## How to judge it

- `ab_harness.py` now holds `RRIGHT` for the whole walk, so a run sweeps the camera.
- Report the replay tail (`submit` p95), not the average: `python3 spin_report.py ab-results/*.log`.
- Then one heavy-scene session in play (2,000+ draws) reading `gpu/vk` replay and `GPU time`.
- Pass: p95 replay below 14.4 ms at ~710 draws with the median unchanged, and no new stalls in the
  heavy scene. Fail: any regression in the median — take it out and ship this tree as it is.
