# What this repository does not contain

This is the Steam Deck build tree, published with its sources so the renderer's licence (GPL-3.0,
which `hookshot_vk.so` links) is satisfied alongside the binaries.

Deliberately **not** included, and not in this repository's history either — the history here starts
at this commit for that reason:

- **Branded artwork.** The builder's icon and the documentation's screenshots came from the upstream
  project's artwork. Supply your own icon if you build the AppImage.
- **`recomplauncher.json`**, which quoted the game's title and version.
- **The pipeline-state lists** (`assets/pipeline_states/`). They were produced by playing, and the
  upstream project argued they contain no game data; they are still generated from this game's
  pipeline set, so they are not redistributed here. Without them a new install's first field load
  draws white for a few seconds while its pipelines compile.

Nothing here contains game code or game data. You build the game from your own copy; no image, save
or dump is part of this repository or of any release on it.
