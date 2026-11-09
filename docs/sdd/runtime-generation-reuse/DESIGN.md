# Runtime-generation reuse: design and feasibility

Date: 2026-11-09. Status: design complete; **no-go for a reuse prototype with the
current launch and installation contracts**. Retain full per-operation validation.
An immutable snapshot is a conditional design direction, not a qualified approach.
No production code, public API, packaging, deployment or consumer behavior changes
are part of this decision.

## Decision and trust boundary

Completed Experiment 0 justifies investigating validation reuse. It does not prove
that validated runtime bytes remain the bytes executed. The missing prerequisite
is an enforceably immutable generation consumed by both the unsandboxed launcher
gate and every sandbox file, without reopening mutable source names. A second
prerequisite is a deliberate freshness contract: continuing an old snapshot after
source corruption or replacement would change today's per-operation rejection
behavior. Neither prerequisite is supplied by the present installer or launcher.

The manifest and package producer are trusted. Hashes establish consistency with
that manifest, not authenticity: an attacker able to replace both can supply a
self-consistent malicious runtime. Host kernel, loader, systemd, bubblewrap and
the parent process are trusted infrastructure. Root/kernel compromise and hostile
control of parent memory are outside the model. Hostile writes to an explicitly
selected runtime tree are in scope for assessing validation-to-execution binding;
this does not grant that tree an independent authenticity guarantee.

| Threat | Current guarantee | Required for reuse |
| --- | --- | --- |
| Accidental corruption of a quiescent package | Each dispatch checks manifest, inventory, regular-file modes, sizes and SHA-256; bad input is unavailable | Preserve checks on acquisition, and explicitly settle how later source corruption revokes eligibility |
| Ordinary concurrent upgrade, deletion or relocation | No atomic generation across validation and launch; may reject, fail to launch or consume changed paths | Acquire one coherent validated generation; replacement never changes an existing lease; new acquisition obeys explicit publication/revocation ordering |
| Hostile runtime-tree mutation | No complete race defense; coherent manifest replacement is not authenticated | Freeze captured bytes before validating them and consume those same bytes; no mutable alias or name may substitute them after publication |

| Approach | Evidence and limitations | Decision |
| --- | --- | --- |
| Full validation every operation | Existing source and Experiment 0 establish cost and quiescent checks; still has path races | Keep as reference, without claiming race freedom |
| Reuse with change detection | Path, size, mtime, mode and watcher events do not bind later execution; same-size edits/restored mtime and races remain. Hashing every file again removes most intended savings and still leaves the launch race | Reject under the stated model |
| Validated immutable snapshot | Can conceptually separate source from execution, but present transport closes descriptors and launches/mounts by path; acquisition, immutability, gate execution and freshness are unproven | No-go pending the prerequisites below |

Neither read-only permissions nor a read-only sandbox bind is evidence that a
host writer cannot alter backing content. An open descriptor pins a file object,
not its bytes. A private directory name alone is not an immutability mechanism.
Watchers may be useful diagnostics; they must never authorize a cache hit.

## Source trace and existing races

Paths in this section are relative to Images unless marked umbrella or consumer.

1. `scripts/prepare-isolated-runtime.py::prepare` discovers the host-native
   helper/plugin ELF dependency closure using `ldd`, copies resolved sources,
   normalizes file modes to 0644/0755, hashes copied bytes and emits a version-1
   manifest. It publishes a new directory with `renameat2` no-replace semantics.
   This avoids replacing an existing preparation output; it neither freezes the
   published files nor provides a coherent snapshot of concurrently changing host
   dependencies. Prepared directories, files and manifest remain writable by
   their owners.
2. `cmake/InstallIsolated.cmake.in` compares built and bundled helper hashes and
   invokes the built helper's `--verify-runtime`. `cmake/Isolated.cmake` then
   copies the directory preserving source permissions. Validation and copying are
   separate operations. Umbrella `scripts/install.sh::copy_stage` installs files
   individually after staging/ownership/collision checks, then publishes its
   ownership manifest. This is not an atomic runtime-generation switch. Preserve
   those installer protections and conservative uninstall behavior unchanged.
3. `src/isolated/client.cpp::run` captures the caller-owned image device, then
   `src/isolated/runtime.cpp::dispatch` calls `validate` on every operation.
   `validate` checks an absolute non-symlink root, a regular 0644 manifest bounded
   by the control limit, version, unique clean `usr/` paths, file modes/sizes,
   SHA-256, required helper/four plugin entries and unexpected tree entries.
   Individual files are bounded at 1 GiB; there is no explicit aggregate-byte cap.
   It returns strings containing `--ro-bind source-path destination-path`.
4. Manifest `lstat` and read, file `lstat` and hashing, inventory traversal and
   later launch are separate observations. Ancestors are not pinned against
   replacement. Hashing can race writes; inventory is not a transaction. After
   validation all hashing descriptors are closed. Replacing the root at the same
   path, or changing any file before bubblewrap opens it, is not prevented.
5. Dispatch executes `/usr/bin/systemd-run --user --scope ...
   runtime/usr/libexec/holonight-images-helper --gate /usr/bin/bwrap ...`.
   The runtime helper is first executed outside the sandbox. `helper.cpp::main`
   waits for `G` before executing bubblewrap, but the gate executable and its host
   dynamic loading have already run. Parent scope-limit verification cannot
   authenticate that earlier execution. QProcess closes descriptors from 3 up.
6. Bubblewrap binds each manifest file read-only into `/usr/...`, creates
   `/proc`, `/dev`, private `/tmp`, `/run`, library symlinks, clears its environment
   and executes the bound helper. Every manifest file matters, including ELF
   interpreter/libraries, plugins and helper, not only the four required codecs.
   No arbitrary host codec tree is mounted. Synthetic sandbox files are not
   runtime inventory; their construction remains per operation. Host launch
   tools and the gate's host loader/dependencies remain a separate trusted base.
7. Each operation retains its fresh helper/scope, 2 GiB memory and zero-swap
   limits, request protocol, 15-second request deadline and hierarchical terminal
   cleanup. `cleanup.cpp` and dispatch release/acknowledgement ordering must not
   become generation-lifetime machinery or be bypassed by reuse.

`cmake/HolonightImagesConfig.cmake.in` exposes a package-relative runtime location;
`tests/isolated-package-test.cmake` copies a prefix to `relocated prefix` and
passes its explicit runtime path to an installed consumer. This proves ordinary
relocated invocation, not in-flight relocation safety. A content identity must
exclude absolute prefixes while an acquisition selection must still identify the
explicit source; identical names at a new path do not inherit validation.

`include/holonight_images/isolated.h` holds only a directory QString.
File Browser's `preview_service.cpp`, `thumbnail_service.cpp`,
`thumbnail_decoder.cpp` and `exif_reader.cpp` frequently construct short-lived
clients. Thumbnails' `src/isolated.cpp` borrows a client. A client-local cache
would therefore often die before a second operation. Images owns synchronous
mechanisms; consumers retain scheduling, workers, caches and lifetime policy.

## Conditional ownership and interface proposal

The following is a future interface sketch, not an API introduced here:

```cpp
// Consumer-owned lifetime; provider implements synchronous generation mechanics.
RuntimeGenerationOwner(sourceSelection, generationLimits);
acquire(cancelled) -> GenerationLease | RuntimeFailure;
replaceSource(newSelection, cancelled) -> GenerationId | RuntimeFailure;
revoke(selectionEpoch); // prevents new leases; does not interrupt existing work
IsolatedClient(GenerationLease); // cheap shared immutable handle, fresh helper/call
```

One long-lived owner belongs to the consumer's preview/runtime service, shared
with its thumbnail, metadata and decode jobs. Pass leases/handles through those
jobs rather than introduce a provider singleton or a pathname-global cache.
Thumbnails continues borrowing the client. Consumer teardown cancels and drains
jobs before releasing its owner; a lease keeps a generation alive through launch,
reply handling and verified terminal cleanup. Interface plumbing and consumer
lifetime changes are prerequisites requiring later scoped implementation.

Generation identity is a versioned digest of exact bounded manifest bytes plus
canonical sorted destination paths, modes, lengths and verified content digests,
with validation-policy and sandbox-layout versions. Manifest byte changes produce
a new identity even if semantically equivalent. Inventory is an exact allowlist;
no extra file or directory enters the snapshot. The source absolute path and a
monotonic selection epoch are acquisition metadata, not content identity. Do not
use a manifest's declared digest as proof that bytes have been validated.

## Lifecycle and freshness rules

1. **Acquire:** serialize construction per selection epoch. Concurrent callers
   join one bounded construction; waiters retain individual cancellation. Open
   the selected source without following substituted symlinks, bound manifest,
   count, depth, paths and total bytes, and capture the exact inventory into
   private storage. Never execute a source helper during acquisition. Observed
   source changes fail the attempt without partial publication or automatic retry.
2. **Freeze then validate:** establish enforceable immutability of captured
   content and namespace first; validate the frozen manifest, exact inventory,
   types, modes, sizes and hashes using the full reference policy. Hashing source
   files and then copying is insufficient. For a mixed source capture to qualify,
   every captured entry must match one captured trusted manifest; claiming an
   atomic source snapshot additionally needs a transactional publisher. A mutable
   copy made read-only does not satisfy this step.
3. **Publish:** atomically publish a complete ready generation only if its source
   epoch is still current and construction has not been abandoned. No client may
   observe a partially initialized generation. A cancelled waiter does not cancel
   other waiters; when none remain, abandon construction at the next bounded
   cancellation point and release unpublished resources.
4. **Launch:** hold a lease. Resolve gate execution and all bind sources from
   that immutable generation exclusively. A sealed-content descriptor approach
   would need proven descriptor propagation through QProcess/systemd-run/gate/
   bubblewrap, executable loading and mount construction. A protected filesystem
   snapshot would need proven no-writable-alias and namespace replacement
   guarantees. Neither is supplied here. Changing only sandbox binds leaves the
   earlier unsandboxed gate vulnerable. Host loader/tool trust must stay explicit;
   any attempt to snapshot that base is a separate packaging/launcher decision.
5. **Invalidate:** do not infer freshness from a cached pathname. An explicit
   source replacement/revocation advances the epoch and blocks new leases from
   the old epoch before validating its replacement. Failed replacement stays
   unavailable for new work, with no stale fallback. Existing leases may finish
   only from the old immutable bytes. Relocation requires explicit new selection
   and validation; matching content may be deduplicated only after validation.
6. **Retire/release:** replacement makes the old generation retired; last lease
   release after terminal cleanup frees it. Dropping an owner cannot unmap live
   launch inputs. Cancellation of an operation retains its lease through cleanup;
   cleanup failure remains `CleanupFailure`, never a successful image result.

**Freshness is an unresolved prerequisite, not an implementation detail.** An
immutable snapshot can safely execute old bytes after the source is corrupted,
but today's next call would validate and reject that source. The current installer
has no authoritative revocation channel and allows file-by-file replacement.
Preserving immediate arbitrary-source-change rejection requires per-acquisition
full verification or another demonstrated authoritative mechanism. Alternatively,
an explicitly approved generation-pinned contract could permit old immutable
bytes until explicit refresh/revocation, paired with a transactional publisher.
That would change observable upgrade/corruption semantics and must not be silently
introduced. TTLs, restart-only refresh and missed watcher events are not substitutes.

## Failures and resource bounds for a later prototype

Acquisition, validation, immutability, descriptor-transfer or launch-binding failure
returns `Unavailable` without a provider result and without source-path fallback.
Malformed worker replies remain `ProtocolFailure`. A pre-launch cancelled caller
returns `Cancelled`; post-launch cancellation follows existing cleanup, whose
failure takes precedence. No failure publishes or poisons a reusable ready entry;
recovery requires an explicit new successful acquisition/selection. Do not cache
negative results indefinitely or retry a changing tree inside one request.

Proposed initial limits (to qualify, not existing guarantees): one active, one
retired and one building generation per owner; at most 128 files and 128 MiB
content per generation; the existing 64 KiB manifest bound; at most 256 generation
descriptors including directories/metadata per generation. Enforce these before
allocation/opening, with bounded streaming copies. Three generations imply at
most 384 MiB captured payload and 768 generation descriptors, plus explicitly
accounted metadata/copy buffers and normal per-operation transport resources.
Measure RSS, backing storage and descriptor counts separately; payload size does
not predict RSS. Source, sealed and launch handles must all count toward the cap.

If a second retired generation would be needed, reject/defer refresh until the
first drains; never evict in-flight bytes. Bound queued acquisition waiters using
the consumer's existing job limit; no provider-created unbounded queue. Use a
separate bounded construction deadline (proposed 15 seconds) and cooperative
cancellation between reads. Blocking filesystem operations require an explicit
interruption/bounded-I/O solution before claiming a hard setup deadline. Terminal
scope cleanup retains its own existing five-second budget. No generation may
hide unaccounted helpers, scopes or workers. These limits and progress guarantees
need qualification; they are another reason this is not a go decision.

## Evidence and savings model

Reuse umbrella `build/preview-iteration-m9uucbpj/{audit,summary,validation}.json`
and its diagnostic/resource/scheduler child reports. The audit identifies frozen
scheduler `build/preview-scheduler-f2c1ty8f` A/B2 and diagnostic
`build/preview-diagnostic-ymcm3gs7` D2, with correction provenance. The precise
artifact hashes and denominators are also retained in the umbrella
[Experiment 0 record](../../../../docs/initiatives/image-isolation.md#corrected-experiment-0-completed-2026-11-09).
The known acceptance-prefix-only install-manifest exception remains as recorded;
no artifact has been rewritten or rebuilt for this design.

The independent validation report records 1,000 completed lifecycle cycles,
280 attribution cases (696 provider operations), 84 resource cases (220 operations)
and 600 scheduler batches, with cleanup verified and no missing timed observations.
The summary reports runtime-validation median **47.1106485 ms**, helper execution
median **1.516 ms**, and readiness median **27.226 ms**. These phases are nested
and medians are not additive. Instrumented D2 timing and separately sampled
resources must not be subtracted from A/B2 scheduler latency to predict speedups.
Warm scheduler batches start zero decoders and offer no runtime-validation saving.

For planning only, let `V = 47.1106485 ms`, `S` be total one-time generation setup
(including capture, freezing and validation), `r` be per-operation reuse overhead,
and `N` operations on one generation. The illustrative validation-work difference
is `N*V - (S + N*r)`; positive break-even needs `N > S/(V-r)` with `r < V`.
This is a median-based cost model, not measured aggregate elapsed time.

| Hypothetical total setup S | First profitable N if r = 0 |
| ---: | ---: |
| 50 ms | 2 |
| 100 ms | 3 |
| 250 ms | 6 |
| 500 ms | 11 |
| 1,000 ms | 22 |

If setup were only one validation and reuse free, avoided validation work would
be `(N-1)*V`: 47.111 ms at N=2, 423.996 ms at N=10, 4,663.954 ms at N=100,
and 32,741.901 ms at N=696. The latter does not claim that all 696 operations
share an owner or that their wall time falls by 32.7 seconds. Real copying,
freezing, contention, per-launch binding and revocation reduce those savings.

Read-only summation of the frozen B2 installed manifest gives **60 entries,
87,198,752 payload bytes and 10,773 manifest bytes**. These fit the proposed
single-generation caps but do not establish snapshot setup cost, descriptor
needs or memory residency. Source inspection already establishes why current
paths cannot qualify; no disposable probe was necessary and no launch guarantee
is claimed from a toy test. No new benchmark matrix or measurement run was made.

## Required future acceptance cases

Use disposable copied fixtures and deterministic barriers, never installed or
frozen experiment runtimes. A later feasibility probe must preserve its source,
commands and results in a fresh ignored evidence directory. Existing runtime
fault and relocated-package tests are reference behavior, not coverage of reuse.

| Case | Required observation |
| --- | --- |
| Unchanged generation and concurrent acquisition | Exactly one successful construction/validation per epoch; all leases share identity; each operation still launches a fresh helper/scope; pixels and typed results match reference |
| Same-size edits with restored mtime, normal edits, truncation | Invalid capture rejected against unchanged manifest; no timestamp-based hit; published immutable bytes cannot change; next-acquisition behavior must satisfy the approved freshness contract |
| Manifest changes, missing/additional files or directories | Revalidate changed manifest; reject inconsistent inventory, duplicates and unsupported versions; no partial publication; consistent new trusted content gets a new identity |
| Permission and symlink changes | Reject special/wrong file modes and substituted root/ancestor/leaf links; no traversal escape; frozen metadata and execution permissions cannot be redirected |
| Directory replacement and same-path upgrade | Barrier before capture, after capture, after validation and before launch; no mixed or substituted execution; replacement obeys epoch ordering and failed refresh has no stale fallback |
| Mutation between validation and launch | Independently target gate, interpreter, libraries, plugins and every bind class; prove launch uses exact validated immutable objects despite source rename/write/unlink; failed mechanism must fail before executing unvalidated gate bytes |
| Concurrent source capture and hostile writes | Mismatch fails without retry; a self-consistent replacement is not claimed authentic; captured content is frozen before hashing and never gains a writable alias |
| Invalid generation then recovery | All joined callers receive failure without ready cache entry; explicit corrected acquisition validates anew and returns independently known pixels |
| Relocation | New explicit relocated prefix, including spaces, validates; identity excludes prefix; active old leases survive source removal from immutable backing only |
| Cancellation and owner teardown | Cancel one waiter without harming others; last-waiter cancellation frees unpublished storage; cancel at publication/launch/reply barriers; lease survives until cleanup/reaping and no cancelled result leaks |
| Retirement and resource exhaustion | Hold old in-flight leases across repeated refresh; enforce generation/byte/FD/waiter caps, including failed builds; release after drain; refusal does not corrupt the active generation |
| Sandbox and cleanup regressions | Per-operation namespaces, minimal environment, mount allowlist, limits, readiness gate, timeout, descendant cleanup and cleanup-failure precedence remain intact; bounded resources after many acquire/release cycles |

Before a go decision, demonstrate an immutable storage/namespace mechanism on the
supported host, an end-to-end launch transport including the gate, enforceable
bounds/cancellation, and an approved publisher/freshness contract. Then run the
focused installed/relocated and runtime acceptance appropriate to those changes.
Do not introduce session reuse or prestarted workers. This design-only step uses
document review, evidence arithmetic and whitespace checks, as requested; builds,
provider CTest and installed-package execution are deferred because no executable
or installation behavior changed.
