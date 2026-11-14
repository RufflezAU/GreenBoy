#!/bin/sh
# Puts this build's icon beside the game and points the Steam shortcut at it.
#
#   ./deck/install-icon.sh [<steam userdata id>]
#
# Steam reads `icon` from each non-Steam entry in shortcuts.vdf. The file is edited as bytes: the one
# entry whose exe names this folder gets the field, everything else is copied through untouched (a
# whole-file rewrite once lost the entry boundaries and Steam discarded the list).
set -eu
GAME=$(cd "$(dirname "$0")/.." && pwd)
ASSETS="$GAME/assets"
VDF=$(ls -d "$HOME"/.local/share/Steam/userdata/*/config 2>/dev/null | head -1)/shortcuts.vdf
[ -f "$VDF" ] || { echo "no shortcuts.vdf found; start Steam once, then run me again"; exit 1; }

[ -f "$ASSETS/greenboy.png" ] || python3 - "$ASSETS" <<'PY'
import sys
from PIL import Image
a = sys.argv[1]
Image.open(a + "/hookshot.png").convert("RGB").resize((256, 256), Image.LANCZOS).save(a + "/greenboy.png", "PNG")
PY
cp -f "$ASSETS/greenboy.png" "$GAME/greenboy.png"
echo "icon: $GAME/greenboy.png"

python3 - "$VDF" "$GAME/greenboy.png" "$GAME" <<'PY'
import os, sys
vdf, icon, game = sys.argv[1:4]
T_MAP, T_STR, T_INT, T_U64, T_END = 0, 1, 2, 7, 8
buf = bytearray(open(vdf, "rb").read())
def rs(p):
    e = buf.index(0, p); return bytes(buf[p:e]).decode("utf-8", "replace"), e + 1
def skip(p):
    while buf[p] != T_END:
        t = buf[p]; p += 1
        _, p = rs(p)
        p = skip(p) if t == T_MAP else (rs(p)[1] if t == T_STR else p + (4 if t == T_INT else 8))
    return p + 1
_, pos = rs(1)
target = None
while buf[pos] == T_MAP:
    start = pos; pos += 1
    k, ke = rs(pos); end = skip(ke)
    if game.encode() in bytes(buf[start:end]).replace(b"\\", b"/"):
        target = (start, end)
    pos = end
if not target:
    sys.exit("no shortcut runs from %s" % game)
start, end = target
body = bytes(buf[start:end])
field = b"\x01icon\x00" + icon.encode() + b"\x00"
if b"\x01icon\x00" in body:
    i = body.index(b"\x01icon\x00"); j = body.index(b"\x00", i + 6) + 1
    new = body[:i] + field + body[j:]
else:
    new = body[:-1] + field + body[-1:]
open(vdf + ".tmp", "wb").write(bytes(buf[:start]) + new + bytes(buf[end:]))
os.replace(vdf + ".tmp", vdf)
print("shortcut icon set in", vdf)
PY
