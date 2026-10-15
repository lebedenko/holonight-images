# HoloNight Images

Use Conventional Commits for every new commit: `type(scope): imperative summary`, or `type: imperative summary` when a scope adds no clarity.

Own synchronous image inspection, bounded raster decoding, SVG source loading/inspection/rasterization and structured metadata.
Use caller-owned seekable devices; never open or resolve a pathname. Keep persistent renderers, animation playback,
caches, workers and UI in consumers. Validate SVG resource policy before loading any renderer; retain Qt resource checks.
Run provider CTest and the installed-package test before handoff. Preserve GPL-3.0-or-later provenance from Viewer.



## Development and documentation

Use `task build` and `task test` for incremental native CMake/CTest work. Native builds
consume installed packages; use `CMAKE_PREFIX_PATH` for an explicit development prefix.
Use `task format` for the pinned formatter and `task check` for container acceptance.
Run `task check:integration` for installation/runtime changes. Container builds use
fresh build/prefix directories, separate from `build/dev` and `build/release`.
clangd reads `build/dev/compile_commands.json` directly.

Routine changes need tests and a commit explanation; update user documentation when
behavior changes. Substantial designs need one local SDD describing intent, decisions,
interfaces and acceptance. Cross-project changes need one umbrella note linking local
designs and stating contracts, dependency order and integration checks. Historical SDDs
remain historical. No separate planning, readiness, handoff or closure commits are required.
Keep routine logs and generated evidence in ignored build directories or CI artifacts.
Provider and consumer implementation may proceed together; publish providers before
consumer commits that reference them. Update umbrella pins per coherent milestone.
