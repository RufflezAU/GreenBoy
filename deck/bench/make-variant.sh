#!/bin/sh
# make-variant.sh <name> [<folder with hookshot and/or hookshot_vk.so>]: a game folder to benchmark, in
# $GB_BENCH/variants/<name>. Its bin/ is a copy of the installed game's ($GB_GAME/bin) with the given binaries over it;
# every other file of the game links to $GB_GAME, so a variant costs only its binaries. Its switches and options are
# the game's configs/stable.env and configs/stable.ini, copied (edit them there, or pass --env to run.py / ab.py).
set -eu
GAME=${GB_GAME:-$HOME/Games/GreenBoy}
V=${GB_BENCH:-$HOME/greenboy-bench}/variants/$1
[ -x "$GAME/bin/hookshot" ] || { echo "no game at $GAME (GB_GAME)" >&2; exit 1; }
rm -rf "$V"
mkdir -p "$V"
for f in "$GAME"/* "$GAME"/.hookshot_*; do
    [ -e "$f" ] || continue
    case "$(basename "$f")" in
        bin|configs|launcher.sh|hookshot_env.txt|hookshot_options.ini*|hookshot_log.txt*|user) ;;
        *) ln -s "$f" "$V/" ;;
    esac
done
cp -a "$GAME/bin" "$V/bin"
if [ -n "${2:-}" ]; then
    for b in hookshot hookshot_vk.so; do
        if [ -f "$2/$b" ]; then cp "$2/$b" "$V/bin/$b"; fi
    done
fi
cp "$GAME/configs/stable.env" "$V/hookshot_env.txt"
cp "$GAME/configs/stable.ini" "$V/hookshot_options.ini"
# (which binaries the variant runs, for the results: the first 16 hex digits of their SHA-256)
sha256sum "$V/bin/hookshot" "$V/bin/hookshot_vk.so" | cut -c1-16 > "$V/binaries.txt"
echo "$V: $(tr '\n' ' ' < "$V/binaries.txt")"
