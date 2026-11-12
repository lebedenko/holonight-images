# Immutable runtime preparation and one-shot standby: feasibility gate

Date: 2026-11-11. Status: **no-go for this iteration; production path retained**.

## Decision

The sole candidate is a system-managed, versioned, read-only SquashFS runtime.
Construction and mounted-generation qualification could not be performed with
the available host tools. Therefore immutability, execution binding, installation
and bounded teardown remain unproven. The supplied stop condition applies before
prepared transactions, generation reuse or standby scheduling are implemented.
This is an environment-limited qualification result, not a finding that SquashFS
cannot meet the contract. No alternative mechanism is substituted.

The [umbrella note](../../../../docs/initiatives/immutable-runtime-standby.md)
records the cross-project outcome. The previous
[generation-reuse assessment](../runtime-generation-reuse/DESIGN.md) and
[source transaction design](../source-preview-transaction/DESIGN.md) remain
historical evidence; their production contracts are unchanged.

## Candidate and required trust boundary

[SquashFS](https://docs.kernel.org/filesystems/squashfs.html) is a read-only
filesystem that stores file data, inode metadata, directories and extended
attributes in an image. Read-only filesystem semantics alone do not protect a
writable backing image or its published name. Qualification requires a
system-owned image and namespace inaccessible to same-user mutation, including
old writable aliases and proc descriptor access. A user-owned image mounted
read-only is insufficient.

[fs-verity](https://www.kernel.org/doc/html/latest/filesystems/fsverity.html)
alone does not freeze file metadata and is not the candidate. No memfd, tmpfs,
FUSE or read-only-bind substitute is introduced.

The initial bounds remain 128 files and 128 MiB uncompressed content per
generation, with at most one current and one retired generation. Acquisition or
refresh exceeding either bound must fail. These are proposed qualification
requirements, not new limits imposed on the mutable production path.

## Reproduced observations

Evidence is retained in umbrella
`build/immutable-runtime-gate-20261111/evidence.json`, including every payload
hash, size and mode. The read-only host capability check ran outside the Codex
sandbox so sandbox restrictions are not mistaken for host limitations.

| Check | Observation | Meaning |
| --- | --- | --- |
| Image construction tools | `mksquashfs`, `unsquashfs` and `sqfstar` absent from host PATH | No construction or image-inspection fixture was available |
| Running kernel | `7.2.15-arch1-1`; matching kernel build config has `CONFIG_SQUASHFS=m` and `CONFIG_SQUASHFS_XATTR=y` | Support is configured as a module; this does not prove mounting works |
| Registered filesystems | SquashFS absent from `/proc/filesystems` | Not registered at observation time; not proof that module loading would fail |
| Disposable namespace | `unshare --user --map-root-user --mount true` exits 0 on host | Namespace creation works; no filesystem mount or privileged installation was tested |
| Existing native runtime | Previous transaction `C/runtime-final`: 60 payload files, 87,201,616 bytes | Payload fits proposed bounds |
| Including manifest | 61 regular files, 87,212,389 bytes | Still below both bounds under the conservative counting convention |
| Full existing validation | Existing helper `--verify-runtime` exits 0; independently checked payload modes, sizes and hashes match | Validates the existing mutable directory only, not an immutable mounted generation |

The checked manifest SHA-256 is
`9500111e25eb43b895e41e48c1794b24286cbddb1668a6621e12d157148e28fd`.
No package installation, module loading, system mount, privileged fixture,
deployment or cleanup recovery was performed. The existing runtime was read only.

## Obligations that remain unproven

| Obligation | Source assessment and missing evidence |
| --- | --- |
| Immutable backing and namespace | No image was constructed or published in a protected system-owned fixture. Mutation through ordinary paths, old aliases, proc descriptors, mode changes and security attributes was not exercised. |
| Validate and execute identical objects | `src/isolated/verification.cpp::verifyRuntime` checks manifest, inventory, regular-file modes, sizes and hashes, then returns pathname binds. `runtime.cpp::dispatch` later executes the runtime helper as the unsandboxed gate and passes those names to bubblewrap. There is no generation lease or mount identity binding. A mounted immutable generation must be validated and retained across every one of these lookups. |
| Explicit host loader boundary | The gate executes before bubblewrap and uses the host ELF loader/dependencies. Host systemd, bubblewrap, launcher and this loader remain trusted infrastructure. The sandbox helper's interpreter, libraries and plugins must come from the validated mounted generation. No mounted execution trace proves that boundary here. |
| Upgrade and selection pinning | Preparation publishes a new mutable directory without replacement; dispatch owns only path strings. There is no current/retired mount registry, selection epoch, active lease retention or fail-closed refresh implementation. |
| Installation and rollback | `cmake/InstallIsolated.cmake.in` validates a bundle and `cmake/Isolated.cmake` installs its directory. Umbrella `scripts/install.sh::copy_stage` reconciles ownership, then installs entries individually and verifies the target. It does not publish versioned mounted images atomically. No staged image ownership/collision or rollback fixture exists. |
| Reboot, removal and bounded teardown | `scripts/uninstall.sh` conservatively removes matching owned files and empty directories. It has no generation mount/loop lifecycle or busy-lease policy. Unmount, detach, crash/reboot recovery and bounded failure behavior have not been demonstrated. A per-request privileged broker is not permitted. |

These are missing proofs, not newly observed production regressions. In
particular, successful validation of a mutable directory does not establish
race-free execution, and passing the size bounds does not qualify the candidate.

## Scope and verification consequence

The plan explicitly makes standby conditional on all gate obligations. Work
therefore stops here. No prepared transaction API, scheduling threads, refresh
behavior, deadlines, caches, UI or installer behavior changes. Mutable development
prefixes retain full validation on demand, as does the existing production path.

No latency comparison, phase profiling or 100-sample benchmark was run: there is
no qualified immutable variant to compare. Historical 42–47 ms validation figures
are not reconfirmed or used to predict savings. The median/p95 targets, memory
budget and correctness/cleanup acceptance criteria remain untested for standby.
No performance improvement is claimed.

Verification consists of capability discovery, the disposable namespace probe,
existing runtime validation, independent inventory/bounds checks, documentation
link review and whitespace checks. Documentation-only changes do not warrant
provider builds, installed-package suites, Core consumers or rendered acceptance
under umbrella proportional-verification guidance. Those checks remain required
if runtime, packaging or consumer contracts are subsequently changed.

Reconsideration requires a construction toolchain and a disposable privileged
fixture that can prove protected publication, hostile mutation rejection, full
mounted validation, pinned gate/sandbox execution and bounded lifecycle handling
through upgrade, rollback, reboot and removal. Until those proofs exist, no pool
implementation is qualified. This report authorizes no host deployment or
publication and changes no umbrella pins.
