# External dependency management — holonight-images

Work package: EDM-009
Audit baseline: `d834984dc413dc9e56f7f3157fa605d6a8667088`
Implementation baseline: `ce9bf6957f6efa51a3f5dbf9f51d95fb9b48cd6f`
Umbrella audit: `38146d8f474317f3f8d72699f60e6d16a71dd165`
Status: Verified locally; publication and gitlink update pending. Ready checkpoint: `318ce54`.

## Requirements

- Configuration and normal build commands shall never acquire dependencies or prepare source providers.
- `task deps` shall explicitly check installed external prerequisites; Images has no internal providers.
- Internal providers shall resolve only from approved prefixes; external packages shall resolve from an explicit
  external prefix or normal system locations.
- Enabled dependency-dependent features shall require their dependencies; minimal profiles shall disable them explicitly.
- Where production components use Qt, discovery shall require >=6.11; private Qt components shall match
  the selected public version exactly.
- Where tests use GTest, consumers shall require installed GTest >=1.14 CONFIG and any GMock targets they use.
- Existing public APIs, component switches, install-tree consumers and acceptance coverage shall be preserved.

## Design

Adopt canonical `tooling/modules/holonight-images.json` and `.cmake`, then synchronize bundle 2.0.0 into this repository.
The copied metadata is owned by this standalone checkout. CMake performs authoritative discovery; shared probes
provide prerequisite diagnostics and record resolved versions/paths. Incompatible caches and local provider install
trees are archived before reuse. Package acquisition occurs only in explicit environment preparation. CI switches
build/runtime/release lanes together to qualified immutable images and runs acceptance offline after preparation.

Preserve existing dependency interfaces and component switches; adopt installed GTest CONFIG discovery where tests use it.

## Implementation and verification tasks

- [x] Confirm the exact baseline and canonical handoff before implementation.
- [x] Adopt declarations, prefix helpers, explicit preparation and compatibility signatures.
- [x] Apply the repository-specific discovery changes above.
- [x] Update Task, CI preparation/entrypoints, Dockerfiles, release lanes and contributor instructions.
- [x] Run declaration/CMake/profile consistency checks and offline missing-package regressions.
- [x] Run narrow regressions, clean acceptance, installed-package consumers and required quality checks.
- [x] Inspect complete logs; record commands, versions, features, warnings and manual checks.
- [x] Make a repository-local commit only after local verification; publish only when authorized.

## Adopted implementation

Canonical origin/main and the clean checkout were confirmed at the implementation baseline on 2026-10-13
with `git ls-remote origin refs/heads/main`. The audit baseline remains historical. The umbrella initiative
remains Accepted. Publication and gitlink updates are separate authorized handoffs.

- `tooling/module.json` and `dependencies.cmake` copy the canonical Images declarations. Bundle 2.0.0 adds
  `external.py`, `external-packages.json`, `providers.cmake` and updates workflow/README/version.
- CMake includes the helper and requires `GTest 1.14 CONFIG` only under `BUILD_TESTING`. Qt >=6.11 and
  pkg-config EXIF/WebP discovery remain authoritative. Public declarations, package version 0.1.0,
  `HolonightImages::Images`, exported Qt/codec dependencies and fuzzing interfaces are preserved.
- Task adds explicit `ci:prepare`. `deps` validates installed prerequisites and records evidence; it builds
  no providers. Ordinary configure/build/test validate without downloading or preparing anything. Explicit
  external/system prefixes and spaces remain supported. Canonical signatures archive incompatible caches.
- `scripts/ci/run.py`, `lane.sh` and `images.json` implement explicit preparation and four lanes:
  `build-test`, `release`, `static-checks`, `licensing`. Missing, mismatched or modified preparation fails
  before containers start. Preparation archives incompatible evidence, acquires only pinned images and
  records their identities, toolchain, installed package inventory and resolved prerequisites.
- Acceptance runs with `--pull=never --network=none`, caller UID/GID, rootless Podman keep-id mapping,
  read-only snapshots/preparation, private XDG/HOME directories and writable disposable work trees.
  Docker is verified on this host; Podman mapping is covered by the launcher fake, with no claim of a
  real Podman run. Parallelism defaults to two. Lane artifacts and full logs persist under `build/ci/`.
- Provider tests keep Release/Ninja/BUILD_TESTING=ON and all three registrations. Release stages `/usr`
  and installs to a separate external prefix containing spaces, then compiles/runs an independent consumer.
  `tests/package-test.cmake` exports compile commands so canonical tidy covers the original install consumer.
  Optional Clang fuzz harnesses build for compatibility without running campaigns or altering retained findings.
- Supplement extraction/download is retired; `prepare-tools.py` now gives remediation and historical
  `packages.json` remains unchanged. Hosted CI explicitly prepares, runs all lanes and uploads evidence.
  README and the historical local-CI SDD link the current contract.

## Separate quality cleanup

Canonical formatting initially passed. Strict tidy exposed existing owned diagnostics. A separate cleanup
commit applies braces, explicit casts, designated initializers, clearer local variable names, const-reference
fixture helpers, nodiscard internal accessors, an encapsulated device failure flag and `std::array` for the
bounded SVG read buffer. Image/SVG assertions and codec coverage remain intact.

Public headers change only lint comments: installed camelCase member names and enum representations are
preserved explicitly. `DecodeOptions` retains caller-supplied aggregate limits, rather than changing their
initialization. Two narrowly scoped complexity annotations preserve the existing ordered SVG resource-policy
validation and decode reader/fallback/outcome precedence in auditable functions. Required libFuzzer entrypoint
names retain targeted naming annotations. No canonical check is disabled globally or CI assertion weakened.

## Environment and verification

Qualified full Arch image:
`ghcr.io/lebedenko/holonight-deps@sha256:37ca051c39d1688d6413c47d94b8c0f221152dac6981ec67d155f2c43ea17b40`.
Separate licensing image:
`docker.io/fsfe/reuse@sha256:85462a75c0f8efda09ddd190b92816b70e7662577c8427429e11e1b9f25a992e`.
There is no reduced Images profile. GCC 16.2.1, CMake 4.4.3, Clang 22.1.8, Python 3.14.7,
Ninja 1.13.2, Qt Core/Gui/Svg 6.11.2, GTest 1.18.0, libexif 0.6.26, libwebp 1.6.0 and
qt6-imageformats 6.11.2 are installed in the qualified environment.

Focused launcher (8) and dependency (11) regressions pass. They cover source snapshots, spaces/modes/symlinks,
missing/mismatched/tampered preparation, archival, offline mounts/rootless user mapping, required failure
propagation, missing EXIF/WebP, normal commands without acquisition, explicit prerequisite validation,
Qt/GTest versions, tests disabled without GTest, system and explicit prefixes, and stale cache archival.
The first external-prefix fixture omitted libwebp's installed libsharpyuv pkg-config dependency; adding its
pc file corrected the fixture and all 11 tests passed in the same offline image. This changed no production
requirement. Initial strict-tidy failure is retained at `build/ci/20261013T091056Z-b4mn01ie`.

## Clean acceptance — 2026-10-13

`python3 scripts/ci/run.py --prepare` passed at `build/ci/20261013T101950Z-twte_w9u`.
Clean `python3 scripts/ci/run.py` passed all four lanes at
`build/ci/20261013T102018Z-x17x6m1i`. Full logs were inspected:

- Release provider tests: all three CTest registrations and all 36 GTest cases pass (19 raster/metadata,
  17 SVG), with no skipped cases. JPEG/PNG/WebP/TIFF, alpha/orientation, device ownership/faults,
  cancellation, metadata budgets and SVG resource-policy coverage remain intact.
- Installed-package CTest builds/runs the original standalone consumer. SVG without image plugins passes
  in its separate process. All three optional Clang/libFuzzer harnesses compile/link; they are not installed.
- Release stages the exact nine expected files under `/usr` and builds/runs a separate consumer using
  `/work/external prefix`. Public version/target/dependency interfaces are unchanged.
- Canonical format and strict tidy pass across all ten owned translation units: three production,
  three provider/plugin tests, one installed consumer and three fuzz harnesses.
- REUSE 6.2.0 passes in its separate pinned image. All eight launcher and eleven dependency regressions
  pass within clean acceptance. Canonical tooling's 32 fixtures pass independently.

Log review found the inherited unused `QML_IMPORT_PATH` preset variable. Images has no QML modules, so it
was removed from all three presets. Explicit preparation was refreshed at
`build/ci/20261013T102406Z-te0rq4u8`; affected release/static lanes then passed at
`build/ci/20261013T102409Z-3aqh6u2h` with no unused-variable warning. All eleven dependency regressions
also passed against the final presets in the same offline qualified image, logged at
`build/dependency-regressions-final.log`. Unaffected Release provider/fuzz acceptance was retained.

Canonical JSON/CMake equality, `python3 tooling/sync.py --check --module holonight-images`,
`python3 tooling/generate-install-profile.py --check`, shell/Python syntax, hosted workflow YAML and
whitespace checks pass. Public header declarations match the baseline after removing comments/whitespace.
The existing assertion/test macro sequences remain unchanged: 161 in image_test.cpp and 91 in svg_test.cpp.
Full identity/package evidence and acceptance reports/log hashes are retained in
[environment.json](verification/environment.json) and [acceptance.json](verification/acceptance.json).
Final documentation licensing is checked before the adoption commit.

## Reviewed diagnostics and limits

No unresolved owned compiler or strict-tidy diagnostics remain. Optional Vulkan-header discovery notices
come from Qt and do not affect these CPU image checks. libpng Read Error and Qt JPEG not-a-file diagnostics
occur only in explicit malformed-input/read-fault/resource-rejection tests; all corresponding assertions
pass. The launcher's fake-runtime failure tests intentionally log failed lanes and missing preparation;
these are passing regressions, not failed acceptance lanes. Tidy's generated warnings are suppressed
non-user Qt/standard-library diagnostics or the documented targeted API/complexity annotations above.

Historical supplemental package identities remain at `scripts/ci/packages.json`. Existing maintenance
fuzz campaign evidence, including the Qt PDF plugin leak finding, remains unchanged in
`docs/sdd/shared-image-maintenance/VERIFICATION.md`. This package includes build smoke checks, not a
new sanitizer campaign. No manual UI interaction is required by Images; downstream/manual ecosystem
checks, real Podman execution and Debian qualification remain later work. Nothing is published or pinned
by this handoff, and the umbrella initiative stays Accepted.
