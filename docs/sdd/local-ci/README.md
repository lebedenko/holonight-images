# Local CI rehearsal

Baseline: c76142cbb69b69c962164f8ed82948d8daa9a367. Umbrella package CI-004.

Preserve the existing build job and push/PR/manual triggers. Use the same pinned
Qt6 6.11.1/compiler image and checksum-pinned official Arch image-codec archives
locally and remotely. Extract codecs into a disposable prefix; retain original
Release/Ninja, BUILD_TESTING=ON and parallelism 2. Run all provider, installed-package
and plugin-isolation CTest cases with output-on-failure and no-tests=error.
The existing repository has no other push-validation jobs.

The launcher snapshots tracked edits and non-ignored new files, omits deleted and
ignored inputs, and reports untracked inputs to add before pushing. Containers only
mount that snapshot read-only; writable source and application build trees are fresh.
Docker is preferred, with Podman fallback when absent, on linux/amd64. Save complete
logs, revision/dirty status, image identity, tool versions and results in ignored
build/ci. Every required failure or missing runtime must return nonzero.

Do not change image-provider behavior or normal development tasks. No pushes,
publication or pin updates. Local acceptance passed on 2026-10-03.


Verification: clean `task ci` passed in build/ci/20261002T220233Z-sjy691tb/
with all three CTest registrations (provider, installed package and SVG without
image-reader plugins). Launcher regressions passed, including missing runtime and
nonzero propagation. Hashes, modes and timestamps confirmed 173 source/development
build files stayed unchanged. Complete logs were reviewed; no compiler warnings
were emitted. Optional Vulkan headers are not needed for these CPU image checks.


Rootless Podman uses `--userns=keep-id` so preserved private file modes remain
readable under the requested UID/GID. A fake-runtime launcher regression verifies
user mapping and the read-only input mount. Podman is not installed on this host;
its real-runtime integration is unverified. The verified Docker path is unchanged.
