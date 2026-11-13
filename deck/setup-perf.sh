#!/bin/sh
# deck/setup-perf.sh -- one time, run with sudo, on the Deck.
#
#   sudo /home/deck/Games/Hookshot-legacy477b/setup-perf.sh
#
# Why this exists: within the Steam Deck's 15 W Van Gogh APU power budget, CPU frequency scaling and GPU clocks share
# one envelope. Pinning all 8 logical CPUs to scaling_governor=performance + energy_performance_preference=performance
# locks the Zen 2 cores at 3.5 GHz (~10 W), starving the RDNA 2 GPU of power and throttling GPU clocks down to
# 200-1040 MHz whenever GPU load rises (outdoor scenes, frame generation). Instead, we want dynamic hardware boost so
# active CPU threads boost to 3.5 GHz while idle cores drop voltage/clocks and leave power headroom for the GPU.
#
# Three standard SteamOS pieces are set up here (once, as root):
#   1. GameMode (installed as standard): the deck user is added to the 'gamemode' group. After that the launcher can
#      call gamemoderun with no polkit password prompt -- the mechanism SteamOS uses while a game is running.
#   2. A systemd unit (hookshot-perf.service) that sets responsive dynamic CPU scaling at boot without starving the
#      15 W APU's GPU:
#        - amd-pstate-epp: scaling_governor=powersave + energy_performance_preference=balance_performance (AMD's
#          autonomous CPPC dynamic boost mode; governor is set before EPP because governor=performance locks EPP).
#        - acpi-cpufreq / passive cpufreq: scaling_governor=schedutil when available (falling back to ondemand).
#      Remove it with: sudo systemctl disable --now hookshot-perf.service
#   3. Zero-copy GPU memory sharing (/dev/udmabuf): with it the game's memory reaches RADV as dma-bufs over the game's
#      own memfd pages. Without it the memory is imported as host pointers, and amdgpu re-validates every page at each
#      command submission (~1 ms a submission on the Deck, several times a frame). The device normally belongs to root
#      and the kvm group, which the deck user is not in; a udev rule gives it to the user's own group instead. The
#      game's log says which it got: "mem: guest memory stays host-pointer imports" or "vk: dma-bufs of at most ...".
#      Remove it with:
#        sudo rm -f /etc/udev/rules.d/71-hookshot-udmabuf.rules /etc/modules-load.d/hookshot-udmabuf.conf
#
# /etc on SteamOS survives updates for a while and is reverted by a major OS upgrade; rerun this if it comes back.
set -e
[ "$(id -u)" = 0 ] || { echo "run me with sudo"; exit 1; }
USER_NAME=${SUDO_USER:-deck}

echo "1. game mode group"
if getent group gamemode >/dev/null 2>&1; then
    gpasswd -a "$USER_NAME" gamemode || true
    echo "   $USER_NAME added to 'gamemode' (takes effect at the next login)"
else
    echo "   no 'gamemode' group on this system; skipping"
fi

echo "2. dynamic cpu scaling at boot (15 W APU safe)"
cat > /etc/systemd/system/hookshot-perf.service <<'EOF'
[Unit]
Description=Responsive CPU scaling without 15W APU GPU power starvation (Hookshot)
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/sh -c 'for d in /sys/devices/system/cpu/cpu[0-9]*/cpufreq; do [ -d "$d" ] || continue; avail=$(cat "$d/scaling_available_governors" 2>/dev/null || true); drv=$(cat "$d/scaling_driver" 2>/dev/null || true); if [ -e "$d/energy_performance_preference" ] && { [ "$drv" = "amd-pstate-epp" ] || [ "$drv" = "amd_pstate_epp" ] || [ "$drv" = "intel_pstate" ]; }; then echo powersave > "$d/scaling_governor" 2>/dev/null || true; echo balance_performance > "$d/energy_performance_preference" 2>/dev/null || true; elif case " $avail " in *" schedutil "*) true ;; *) false ;; esac; then echo schedutil > "$d/scaling_governor" 2>/dev/null || true; if [ -e "$d/energy_performance_preference" ]; then echo balance_performance > "$d/energy_performance_preference" 2>/dev/null || true; fi; elif [ -e "$d/energy_performance_preference" ] && case " $avail " in *" powersave "*) true ;; *) false ;; esac; then echo powersave > "$d/scaling_governor" 2>/dev/null || true; echo balance_performance > "$d/energy_performance_preference" 2>/dev/null || true; elif case " $avail " in *" ondemand "*) true ;; *) false ;; esac; then echo ondemand > "$d/scaling_governor" 2>/dev/null || true; fi; done'

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable hookshot-perf.service
systemctl restart hookshot-perf.service

echo "3. the game's memory shared with the GPU without a copy (/dev/udmabuf)"
modprobe udmabuf 2>/dev/null || true
if [ -e /dev/udmabuf ]; then
    USER_GROUP=$(id -gn "$USER_NAME")
    printf 'KERNEL=="udmabuf", GROUP="%s", MODE="0660"\n' "$USER_GROUP" > /etc/udev/rules.d/71-hookshot-udmabuf.rules
    # (a loadable module is loaded at boot too; built into the kernel, it is always there)
    if [ -e /sys/module/udmabuf/initstate ]; then echo udmabuf > /etc/modules-load.d/hookshot-udmabuf.conf; fi
    udevadm control --reload 2>/dev/null || true
    # (now, without waiting for the next boot)
    chgrp "$USER_GROUP" /dev/udmabuf && chmod 0660 /dev/udmabuf
    echo "   $(ls -l /dev/udmabuf)"
else
    echo "   no /dev/udmabuf on this kernel; skipping (the game keeps host-pointer imports)"
fi

echo "4. what it is now"
if [ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver ]; then
    echo "   driver: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver)"
fi
printf '   governors: '
for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
    [ -r "$c" ] && printf '%s ' "$(cat "$c")"
done
echo
if [ -r /sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference ]; then
    printf '   epp:       '
    for c in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/energy_performance_preference; do
        [ -r "$c" ] && printf '%s ' "$(cat "$c")"
    done
    echo
fi
if [ -r /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq ] && [ -r /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq ]; then
    echo "   scale (first core): $(( $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq) / 1000 )) MHz requested, ceiling $(( $(cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq) / 1000 )) MHz"
fi

echo
echo "done. Log out and back in (or reboot) so the group membership applies, then play."
echo "to undo:  sudo systemctl disable --now hookshot-perf.service && sudo gpasswd -d $USER_NAME gamemode"
echo "          sudo rm -f /etc/udev/rules.d/71-hookshot-udmabuf.rules /etc/modules-load.d/hookshot-udmabuf.conf"
echo "          sudo rm -f /etc/systemd/system/hookshot-perf.service && sudo systemctl daemon-reload"
