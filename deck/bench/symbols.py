"""A sampled frame ("module+offset", as HOS_SAMPLE_ALL writes it) by its symbol, with scripts/prof.py's symbol tables:
the binaries in RX_MAPS=<folder> (the variant's bin/), else the build. Frames outside the game and the renderer stay
their module's name, so libc and the driver read as one frame each."""
import bisect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
import prof  # noqa: E402

_maps = None
_cache = {}


def name(frame):
    global _maps
    if _maps is None:
        _maps = prof.load_symbols()
    if frame in _cache:
        return _cache[frame]
    mod, _, off = frame.rpartition("+")
    n = mod
    if mod in _maps:
        addrs, names = _maps[mod]
        try:
            i = bisect.bisect_right(addrs, int(off, 16)) - 1
        except ValueError:
            i = -1
        if i >= 0:
            n = prof.module_name(mod) + ":" + prof.demangle(names[i])
    _cache[frame] = n.replace(";", ",")
    return _cache[frame]
