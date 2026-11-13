# Security audit — 2026-11-14

Scope: this repository's tree and the build in its release. Read as source, not executed.

## Findings

### 1. High — the update check pointed at a namespace anyone can now claim

`host/hos_update.c` (Windows and POSIX paths), `builder/linux/linux_update.py` and `builder/setup/setup.c`
fetched from `github.com/NotRexed/Hookshot`. That account is **gone** — `api.github.com/users/NotRexed`
returns 404 and `github.com/NotRexed/Hookshot` does not redirect, so it was not a rename. GitHub user and
organisation names can be re-registered once released, and on Linux the program reached the network by
shelling out to `curl` against a URL built from that name.

Whoever registers that name inherits the update channel of every build already installed: a crafted
release note, parts list or AppImage would be offered to players by their own copy of the program. This is
a supply-chain exposure, not a broken link.

**Fixed.** Every such URL is now `RufflezAU/GreenBoy`, and the check is **opt-in**: it runs only with
`HOOKSHOT_CHECK_UPSTREAM=1`. A default build makes no outbound request at all.

### 2. Medium — the program contacted the network by default

The check was on unless `HOOKSHOT_NO_UPDATE_CHECK` said otherwise, i.e. every launch phoned home. Even
pointed at the right repository that is an outbound request the user did not ask for. Now off by default
(see 1), with `HOOKSHOT_NO_UPDATE_CHECK=1` still honoured as a belt-and-braces switch.

### 3. Medium — "report a bug" sent people to a page anyone can own

`gpu/vk/vk_bug_report.cpp`, `gpu/vk/pipeline_share.h` and every language in `gpu/vk/menu_i18n.h` linked to
`github.com/NotRexed/Hookshot/issues/2034` and asked the user to attach a generated archive. That archive
holds logs — file paths, usernames, GPU and driver details — and the destination is re-registrable.
Repointed to our repository's issue page.

### 4. Low — application identity was still the upstream project's

`io.github.NotRexed.Hookshot` (the game window's app id / desktop file name) and
`NotRexed.Hookshot.Builder` (Windows AppUserModelID). Both now `io.github.RufflezAU.GreenBoy` and
`RufflezAU.GreenBoy.Builder`, so the window, the desktop entry and the taskbar grouping name this build.

### 5. Info — what else is in the tree, and why it is fine

- **Other hosts referenced in text and build scripts**: `docs.vulkan.org`, `code.videolan.org`,
  `git.eden-emu.dev`, `raw.githubusercontent.com`, `wixtoolset.org`, `semver.org`, `w3.org`. Build-time
  references and documentation links; none is a runtime callback.
- **`127.0.0.1`** — the debug/emulator bridge. Local only.
- **Discord**: the readme's invite link and the dev-notes file that linked Discord threads are removed.
  The *Discord rich-presence integration* stays: it writes to a local IPC socket and is optional.
- **Credentials**: no tokens, keys, passwords or private URLs in the tree.
- **Attribution that must stay**: `host/mods.c` cites `NotRexed/SkyboundTotk` under MIT. That notice is a
  licence condition, not a pointer — removing it would breach the licence. The same is true of the GPL
  notices around the renderer, which is why the source is published alongside the binaries.

### 6. Info — game references remaining

The upstream manual in `docs/` still uses the game's own vocabulary (controller layouts, the instrument's
note names). That is documentation of a program that plays a game, not game data. No game code, no ROM, no
keys, no executable of the game, and no game-derived pipeline lists are in this repository or its releases.

## How this was checked

`grep -rnE 'https?://'` over the tree, then each host read in place; the update path read end to end
(`hos_update_check` → `latest_tag` → `pipe_tag` → `popen`); every `NotRexed` occurrence classified as code,
documentation or licence notice; the release's asset list compared against the tree.
