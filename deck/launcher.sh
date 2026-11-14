#!/bin/sh
# Steam Deck launcher: stages the chosen config, enables zero-copy memfd/udmabuf when sysfs hides size_limit_mb,
# suppresses multi-GB exit core dumps, and starts the game (under GameMode when permitted).
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
GAME_DIR=${HOS_GAME:-$SCRIPT_DIR}
if [ ! -x "$GAME_DIR/bin/hookshot" ] && [ ! -x "$GAME_DIR/hookshot" ] && [ -d /home/deck/Games/Hookshot-legacy477b ]; then
    GAME_DIR=/home/deck/Games/Hookshot-legacy477b
fi
cd "$GAME_DIR" || exit 1

CFG=${HOS_CONFIG:-stable}
if [ -z "${HOS_ENV_FILE:-}" ] && [ -f "configs/$CFG.env" ]; then
    cp -f "configs/$CFG.env" hookshot_env.txt
fi
if [ -f "configs/$CFG.ini" ]; then
    cp -f "configs/$CFG.ini" hookshot_options.ini
fi

# host/hos_main.c (reserve_guest) opens /dev/udmabuf O_RDWR and checks /sys/module/udmabuf/parameters/size_limit_mb > 0
# before backing guest memory with a shared memfd (whose freed pages host/hos_mem.c discards via MADV_REMOVE instead of
# MADV_DONTNEED). Where udmabuf is built in without a readable size_limit_mb (or mode 0600), gpu/vk/vk_memory.cpp still
# defaults to 64 MB dma-buf pieces, so opt into HOS_GUEST_MEMFD=1 -- but ONLY when:
#   1. HOS_GUEST_MEMFD is not already set in the environment or the env file (load_hookshot_env lets process env win, so
#      exporting unconditionally would clobber HOS_GUEST_MEMFD=0 in either place), and
#   2. /dev/udmabuf is a character device with BOTH read and write access (matching open(..., O_RDWR); forcing a shared
#      memfd when /dev/udmabuf cannot be opened O_RDWR breaks host-pointer fallback on RADV with INVALID_EXTERNAL_HANDLE).
ENV_FILE=${HOS_ENV_FILE:-hookshot_env.txt}
if [ -z "${HOS_GUEST_MEMFD+x}" ] &&
   ! grep -Eq '^[[:space:]]*HOS_GUEST_MEMFD=' "$ENV_FILE" 2>/dev/null &&
   [ ! -r /sys/module/udmabuf/parameters/size_limit_mb ] &&
   [ -c /dev/udmabuf ] && [ -r /dev/udmabuf ] && [ -w /dev/udmabuf ]; then
    export HOS_GUEST_MEMFD=1
fi

[ -f hookshot_log.txt ] && mv -f hookshot_log.txt hookshot_log.txt.old.txt
# No core dump. This process is 495 MB with ~2.5 GB mapped, and SteamOS pipes cores to a Python submitter: a crash while
# closing had the kernel write that out and the desktop was unusable for seconds afterwards. The log keeps the message.
ulimit -c 0 2>/dev/null

# Packaged Linux builds place the game binary at bin/hookshot (with ./hookshot as the Builder GUI wrapper script);
# standalone/dev builds place the binary directly at ./hookshot.
GAME_BIN=./hookshot
if [ -x ./bin/hookshot ]; then
    GAME_BIN=./bin/hookshot
fi

# GameMode is SteamOS's per-game daemon for scheduler/power hints while a game runs. Use it only when the user is in the
# 'gamemode' group (deck/setup-perf.sh adds them once) and HOS_GAMEMODE!=0; without group membership gamemoded raises a
# polkit password dialog at launch, which must never happen in Gaming Mode.
case " $(id -Gn 2>/dev/null) " in
    *" gamemode "*) gamemode_ok=1 ;;
    *) gamemode_ok=0 ;;
esac
if [ "${HOS_GAMEMODE:-1}" != 0 ] && [ "$gamemode_ok" = 1 ] && command -v gamemoderun >/dev/null 2>&1; then
    exec gamemoderun "$GAME_BIN" "$@" > hookshot_log.txt 2>&1
fi
exec "$GAME_BIN" "$@" > hookshot_log.txt 2>&1
