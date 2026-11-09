# Runtime-generation reuse: design and feasibility

Date: 2026-11-09. Status: explicit-refresh contract approved; **sealed-memfd
feasibility probe stopped with no-go at the metadata immutability gate**.
Metadata contract review complete: retain exact modes; no narrowing proposed.
Retain full per-operation validation in production. An immutable snapshot remains
a conditional design direction, not a qualified approach.
No production code, public API, packaging, deployment or consumer behavior changes
are part of this decision.

## Decision and trust boundary

Completed Experiment 0 justifies investigating validation reuse. It does not prove
that validated runtime bytes remain the bytes executed. The missing prerequisite
is an enforceably immutable generation consumed by both the unsandboxed launcher
gate and every sandbox file, without reopening mutable source names. A second
prerequisite is a deliberate freshness contract: continuing an old snapshot after
source corruption or replacement would change today's per-operation rejection
behavior. Explicit refresh is now approved for this experiment and a later
qualified prototype; it is not implemented in production. The immutable-execution
prerequisite remains unmet by the tested mechanism.

The manifest and package producer are trusted. Hashes establish consistency with
that manifest, not authenticity: an attacker able to replace both can supply a
self-consistent malicious runtime. Host kernel, loader, systemd, bubblewrap and
the parent process are trusted infrastructure. Root/kernel compromise and hostile
control of parent memory are outside the model. Hostile writes to an explicitly
selected runtime tree are in scope for assessing validation-to-execution binding;
this does not grant that tree an independent authenticity guarantee.

| Threat | Current guarantee | Required for reuse |
| --- | --- | --- |
| Accidental corruption of a quiescent package | Each dispatch checks manifest, inventory, regular-file modes, sizes and SHA-256; bad input is unavailable | Preserve checks on construction/refresh; a ready immutable generation stays eligible until explicit refresh |
| Ordinary concurrent upgrade, deletion or relocation | No atomic generation across validation and launch; may reject, fail to launch or consume changed paths | Acquire one coherent validated generation; replacement never changes an existing lease; new acquisition obeys explicit publication/revocation ordering |
| Hostile runtime-tree mutation | No complete race defense; coherent manifest replacement is not authenticated | Freeze captured bytes before validating them and consume those same bytes; no mutable alias or name may substitute them after publication |

| Approach | Evidence and limitations | Decision |
| --- | --- | --- |
| Full validation every operation | Existing source and Experiment 0 establish cost and quiescent checks; still has path races | Keep as reference, without claiming race freedom |
| Reuse with change detection | Path, size, mtime, mode and watcher events do not bind later execution; same-size edits/restored mtime and races remain. Hashing every file again removes most intended savings and still leaves the launch race | Reject under the stated model |
| Validated immutable snapshot | Explicit refresh settles freshness; tested parent-owned sealed memfds leave exact mode metadata mutable; end-to-end execution remains unproven | No-go pending the prerequisites below |

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
refresh(sourceSelection, cancelled) -> GenerationId | RuntimeFailure;
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
5. **Explicit refresh:** source edits, deletion, replacement or relocation do not
   automatically invalidate a ready generation; new acquisitions keep using it
   until explicit refresh/revocation. Serialize refresh requests. Refresh advances
   the selection epoch and blocks new leases before validating the replacement.
   Success publishes the replacement; failure leaves new acquisitions unavailable,
   without stale fallback. A later explicit refresh can recover. Existing leases
   may finish only from their original immutable generation. Selecting a relocated
   source requires explicit refresh and validation; content identity excludes its
   path. Refuse further refresh work while retained generations exhaust the bounds
   below, without allocating another generation or evicting live leases.
6. **Retire/release:** replacement makes the old generation retired; last lease
   release after terminal cleanup frees it. Dropping an owner cannot unmap live
   launch inputs. Cancellation of an operation retains its lease through cleanup;
   cleanup failure remains `CleanupFailure`, never a successful image result.

**The generation-pinned explicit-refresh contract is approved.** This deliberately
permits old validated immutable bytes after source corruption, unlike today's
per-operation rejection. Approval does not qualify the storage or implement reuse.
There is no automatic installer revocation channel, TTL or watcher-based freshness
check. A transactional source publisher is not required to keep an already captured
generation usable: replacement capture must match its captured manifest or fail
closed. This does not establish authenticity or an atomic source snapshot.

## Failures and resource bounds for a later prototype

Acquisition, validation, immutability, descriptor-transfer or launch-binding failure
returns `Unavailable` without a provider result and without source-path fallback.
Malformed worker replies remain `ProtocolFailure`. A pre-launch cancelled caller
returns `Cancelled`; post-launch cancellation follows existing cleanup, whose
failure takes precedence. No failure publishes or poisons a reusable ready entry;
recovery after failed refresh requires a later explicit successful refresh. Do not
automatically retry a changing tree inside one request or silently serve old leases
to new acquisitions while unavailable.

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
needs or memory residency. The subsequent storage probe below does not qualify
full-generation capture or launch and runs no benchmark matrix.

## Sealed-memfd feasibility result (2026-11-09)

**No-go for a later production prototype using this mechanism under the required
exact-mode immutability contract.** The approved experiment stops at its first
failed storage guarantee; it does not explore alternative implementations.

Evidence is in ignored Images `build/runtime-memfd-feasibility-eYAKqdW8/`:
`probe.cpp`, `run.py`, `commands.txt`, `provenance.json`, `results.json`,
`execution.json`, `verification.json`, build/diagnostic logs, copied manifest and
before/after source inventories. Reproduce with `python3 run.py` from that directory.
The initial link attempt needed `-fPIC` for host Qt; its diagnostic is retained in
`build-initial-no-pic.log`. The corrected build passed `-Wall -Wextra -Werror`.

Input was the frozen umbrella
`build/preview-scheduler-f2c1ty8f/B2/prefix/libexec/holonight-images/runtime`.
The runner read and hashed all 60 declared payloads, checked their declared modes
and sizes, and copied only the helper into a disposable source tree for this
early capability check. It did not run the frozen helper. The helper's SHA-256 was
`87293cfd1128c3b1f05644bdd9c8051d230a7e7ddc40189b9b487d17d853551b`;
exact manifest, probe and runner hashes are in provenance. Before/after inventory
records matched: no frozen or installed runtime was changed.

Host: Linux `7.2.14-arch1-1`, x86_64, GCC `16.2.1`, Qt Core `6.12.0`.
The private C++/Qt probe copied the 250,344-byte helper to a parent-owned memfd,
set mode `0755`, established seals, then compared captured bytes with the copied
input. It tested `MFD_EXEC | MFD_ALLOW_SEALING | MFD_CLOEXEC` with both content-only
seals and content seals plus `F_SEAL_EXEC`. A separate same-user QProcess attempted
chmod through `/proc/<owner-pid>/fd/<fd>`, with `CloseFileDescriptors` from fd 3
and `CreateNewSession` preserved. No parent-memory modification or inherited
generation descriptor was needed for those attempts.

| Observation | Content seals (`0x0f`) | With `F_SEAL_EXEC` (observed `0x3f`) |
| --- | --- | --- |
| Write, shrink, grow, shared writable mapping | All rejected with `EPERM` | All rejected with `EPERM` |
| chmod `0755` to `0644` through owner proc path | Succeeded | Rejected with `EPERM` |
| chmod to `0777` through owner proc path | Succeeded | Succeeded |
| Captured bytes after attempts | Same SHA-256 | Same SHA-256 |

The execution-bit seal therefore did not freeze exact permission metadata. This
is a metadata counterexample, not evidence that content seals were bypassed or
that arbitrary helper bytes executed. Exact validated modes are part of the
required contract; silently weakening that requirement would be a different
experiment. The failed guarantee is sufficient to stop before full capture and
validation, executable loading or bubblewrap mounting.

Resource observations are limited to this storage check: one 250,344-byte memfd
at a time, two sequential variants, six chmod children all exited and reaped,
and parent descriptor counts restored from 5 to 5. The probe also holds ordinary
QByteArray copies; this is not a generation memory measurement. `execution.json`
records cumulative child maximum RSS including compilation, explicitly not runtime
RSS. No scope, sandbox or runtime helper was launched. No hierarchical cleanup
claim follows from reaping these simple children.

Full manifest/inventory validation of a sealed generation, gate and sandbox
execution identity, known protocol pixels, concurrent acquisition, explicit refresh,
cancellation, owner teardown and repeated bounded lifecycle tests were **not
reached**. The 128-file, 128-MiB, 256-descriptor, 64-KiB-manifest limits and one
active/retired/building lifecycle remain unqualified requirements, not measured
guarantees. No private owner was implemented after the prerequisite failed.
This early stop follows the supplied stop gate and proportional verification;
there is no production change, performance claim, fallback or package rebuild.

## Metadata contract review (2026-11-09)

**Recommendation: retain exact mode immutability and the no-go.** Exact read/write
bits are not intrinsically necessary to keep sealed bytes unchanged. That narrower
fact does not establish equivalent execution integrity: special bits, ownership,
security attributes and legitimate descriptor access have not been qualified.
This review therefore does not propose replacement contract wording or authorize
another memfd launch experiment. A future narrowing requires a separately stated
contract and explicit approval; the original probe remains no-go under its original
contract even if a different contract is later approved.

### Three distinct kinds of metadata

`runtime.cpp::validate` checks source regular-file type, exact `07777` mode, size,
hash and inventory. It does **not** validate UID/GID, ACLs or security xattrs.
Those omissions are observations about current code, not guarantees that such
attributes are harmless. Acquisition must retain its existing source mode and
inventory checks, including rejecting special bits. Capturing bytes into new
storage must not implicitly copy source ownership, ACLs or file capabilities.

Generation identity records the **validated source modes**, manifest bytes,
destination names and content digests described above. Those immutable records
are distinct from a live backing inode's mode/owner/xattrs. Replacing an identity
record with a later `fstat` result would silently change the identity definition;
hashing metadata once does not enforce it. Source location remains excluded.

At launch the kernel uses live backing metadata, not the generation digest.
The unsandboxed gate is exec'd before its `main` waits for `G`; its ELF interpreter
and dependencies load in the host environment. The parent’s scope-limit check is
too late to protect that execution. Bubblewrap subsequently opens bind sources;
read-only mounts restrict that mount's operations, not mutations through another
host alias. Inside the sandbox the interpreter, libraries and Qt plugins open and
map the bound objects. Library permission denial must not silently select another
dependency or lose a required codec. Existing minimal environment and inventory
are necessary but do not prove the proposed descriptor path works end to end.
See `runtime.cpp::dispatch`, `helper.cpp::main`, and the primary descriptions of
[ELF execution](https://man7.org/linux/man-pages/man2/execve.2.html) and
[loader search and secure execution](https://man7.org/linux/man-pages/man8/ld.so.8.html).

### Actors and access paths

| Actor | In-scope capability | Boundary and required outcome |
| --- | --- | --- |
| Source-tree writer | Replace names, bytes, modes and source metadata during capture or later | Captured content must match the captured trusted manifest; later source mutation cannot redirect a lease. A coherently replaced manifest is still not authenticated. |
| Separate same-user process | Follow owner proc descriptors where access checks allow; chmod was observed without inherited FDs or parent-memory access | Remains in scope. Seals must protect bytes through every alias; metadata protection cannot assume this actor is absent. Include already-open aliases when evaluating a new restriction. |
| Compromised sandbox helper | Operate on visible mounts/descriptors, attempt metadata changes and launch descendants | Read-only binds and private proc are intended boundaries; retained host FDs, pre-namespace source opens and namespace capabilities need explicit qualification. Sandbox isolation is not proof about the earlier host gate. |
| Trusted parent and launch infrastructure | Construct storage, choose mappings, retain/release descriptors and start tools | Must enforce publication, identity and cleanup. Parent-memory takeover and root/kernel compromise remain excluded; ordinary proc access does not become excluded merely because it targets the parent. |

### Invariants, effects and evidence

The table separates enforced observations from prerequisites. “Unqualified” means
no guarantee is claimed for the preserved host or any later configuration.

| Invariant / attribute | Purpose and mutation effect | Enforcement and remaining uncertainty |
| --- | --- | --- |
| Exact acquisition modes and inventory | Reject malformed sources and special bits; fixes identity inputs | Existing validator plus future frozen-capture validation. Current path checks still race; snapshot capture remains unimplemented. |
| Fixed bytes and lengths | Prevent code substitution and changed mapped pages | Preserved probe rejected write/shrink/grow/shared writable mapping; [v7.0 `memfd_add_seals`](https://raw.githubusercontent.com/torvalds/linux/v7.0/mm/memfd.c) makes seals inode-wide and irreversible. Require explicit write/grow/shrink/seal seals on every file, including non-executable libraries; `F_SEAL_FUTURE_WRITE` alone is insufficient. Full generation remains unqualified. |
| Read/write permission bits | Adding write permission does not undo content seals. Read removal can deny later opens; read addition can broaden disclosure when an access path exists. Neither alone substitutes bytes | `0755 → 0777` is observed. [chmod semantics](https://man7.org/linux/man-pages/man2/chmod.2.html) concern access permissions, not content sealing. Runtime payloads start world-readable, but this is no confidentiality guarantee for unrelated owner descriptors. Required-library denial/fallback behavior is unqualified. |
| Execute bits | Prevent adding/removing direct execution permission | [v7.0 `shmem_setattr`](https://raw.githubusercontent.com/torvalds/linux/v7.0/mm/shmem.c) checks only changes in `0111` for `F_SEAL_EXEC`. Preserved execute-removal rejection agrees. Library executable mappings are a separate operation: [mmap](https://man7.org/linux/man-pages/man2/mmap.2.html) has descriptor and mount constraints; a mode without X is not a general code-execution prohibition. |
| Setuid/setgid; sticky bit | Set-ID can change credentials and thereby loader behavior; sticky on a regular payload is not a byte-substitution mechanism | The `0111` seal check does not cover these bits. [v7.0 `setattr_prepare`](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/attr.c) applies owner/capability and group rules, not exact-mode sealing. Same-user ownership alone is not proof that set-ID is ineffective in every consumer credential context. No special-bit probe exists. |
| UID/GID | Controls DAC and meaning of set-ID; group changes can alter access/disclosure without changing content | The same [v7.0 attribute checks](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/attr.c) restrict arbitrary UID changes but permit an owner to select an eligible group. Content seals do not establish fixed ownership. Capability-bearing/idmapped consumers are unqualified. |
| ACLs, `security.capability`, LSM/IMA labels, `user.*` / `trusted.*` | ACLs affect access; capabilities can affect privilege on exec; security policy may permit/deny or alter execution context. Ordinary opaque user attributes are not ELF bytes | [v7.0 xattr checks](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/xattr.c) delegate security/system policy and restrict trusted attributes; [capabilities](https://man7.org/linux/man-pages/man7/capabilities.7.html) governs file capabilities. There is no demonstrated metadata seal. Actual memfd ACL/xattr support, permitted setters and LSM effects must be enumerated on the target host; unsupported operations must be distinguished from denied ones. |
| Stable object-to-destination mapping | Prevent FD reuse/name replacement redirecting gate or binds | Trusted parent must retain each exact object until terminal cleanup; namespace map must be immutable. Current probe does not test transport, mount identity or descriptor-number reuse. |
| No metadata-induced privilege gain or alternate loading | Protect execution before and after sandbox entry | A future relaxation would need protections effective **before the first gate exec**, plus verified loader identity and failure behavior. Exact modes alone also do not establish an xattr/ownership policy. These are prerequisites, not properties supplied by content seals. |

### Proc restrictions and privilege protections are not drop-in fixes

[v7.0 proc link resolution](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/proc/base.c)
uses `PTRACE_MODE_READ_FSCREDS`; [proc_pid_fd](https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html)
also distinguishes proc access from permission to reopen the backing inode.
[ptrace access checks](https://man7.org/linux/man-pages/man2/ptrace.2.html) include
credentials, target dumpability, capabilities and LSM policy. Setting the owner
non-dumpable denies ordinary separate launch descendants as well as the attacker;
ancestry does not override that check. Previously acquired aliases are not revoked
by denying future proc lookup. Yama's attach restrictions are not a solution:
[v7.0 Yama](https://raw.githubusercontent.com/torvalds/linux/v7.0/security/yama/yama_lsm.c)
applies its scope restriction to `PTRACE_MODE_ATTACH`, whereas this link check uses
READ. `PR_SET_PTRACER` is not a general exemption from dumpability checks.

The current QProcess closes FDs from 3 and then starts systemd-run in scope mode.
A parent-proc-path design would require systemd-run's gate exec and bubblewrap's
bind-source lookup to reach the owner. Blocking those paths blocks that design.
Keeping inherited FDs, explicit transfer or a separate owner would require a new
transport proof across every exec, credential and namespace transition, including
whether a recipient's own proc descriptors expose the objects again. No such
change is proposed here. Process-wide dumpability changes also affect consumers
outside Images and cannot be introduced as an incidental fix.

[v7.0 `no_new_privs`](https://www.kernel.org/doc/html/v7.0/userspace-api/no_new_privs.html)
can suppress exec-time set-ID and file-capability gains and is inherited, but must
be effective before gate exec. Setting it in the gate is too late. It does not
freeze metadata, remove existing privileges or establish all LSM transitions.
It could also prevent a setuid bubblewrap configuration from acquiring privileges
it needs. A user-namespace-based unprivileged configuration and the actual
QProcess → systemd scope → gate → bubblewrap chain need qualification before this
could support a narrower contract. Do not infer `nosuid` from `--ro-bind`, or assume
sandbox protections apply to host execution through the original memfd mount.

### Version and host limits

The versioned source review above is **Linux v7.0**, not a claim to have audited
the probe's Arch `7.2.14-arch1-1` source and patches. Local headers do not supply
the relevant implementation files; matching host source/configuration remains a
prerequisite. The preserved evidence establishes only the recorded host's tested
operations, with `vm.memfd_noexec=0`, UID 1000 and the recorded Qt/compiler versions.
[v7.0 memfd execution controls](https://www.kernel.org/doc/html/v7.0/userspace-api/mfd_noexec.html)
describe explicit `MFD_EXEC`, `MFD_NOEXEC_SEAL` and hierarchical PID-namespace
policy. A policy that forbids executable memfds must fail closed, without reverting
to mutable files or omitted flags. Older kernels lacking required seals, different
proc restrictions, capability-bearing launchers, setuid bubblewrap, idmapped
mounts and unreviewed LSM policies are unsupported by this evidence. Their failure
or compatibility cannot be inferred from the single successful chmod path.

### Bounded next experiment specification — not executed or authorized here

The unmet property is an enforceable binding of validated bytes **and exact modes**
to every execution/mount consumer, with a qualified ownership/security-attribute
policy. A different mechanism must prevent hostile metadata mutation through all
aliases while preserving legitimate consumption. Repeating the same memfd storage
check cannot meet that property. Use the following ordered gates for a separately
scoped candidate; stop at the first failure and retain evidence, without fallback.

1. **Static mechanism gate:** identify the new enforcement mechanism and matching
   host kernel/tool sources, credentials, mount flags, xattr/LSM policy and alias
   graph. Explain why unauthorized mutation is impossible and how legitimate
   consumers obtain access. If that cannot be shown, stop without native work.
   Any narrower contract must first be written and explicitly approved.
2. **Metadata-only gate:** disposable helper/library copies, one candidate at a
   time, at most four mutation children and the existing byte/FD caps. Attempt
   read/write removal and addition while preserving X (`0111`, `0555`, `0777` for
   a `0755` helper), execute removal/addition on helper and `0644` library,
   setuid/setgid/sticky addition, eligible GID changes, ACLs and relevant xattrs.
   Test separate same-user owner-proc access and previously opened aliases.
   Exact mode mutation is an immediate no-go under the retained contract;
   unexplained metadata effects also stop. Record errno, before/after metadata,
   identity, child reaping and descriptor baseline. Reuse existing memfd write
   and seal observations; do not rerun them absent changed relevant inputs.
   Bound each case to 15 seconds plus five seconds for cleanup; failure to
   terminate and reap within that budget stops the experiment.
3. **Transport gate:** only after storage passes, exercise the real QProcess /
   systemd scope / gate / bubblewrap chain with diagnostic disposable binaries.
   Test both attacker denial and legitimate consumers at deterministic barriers;
   any proc restriction that breaks consumers stops. Verify gate object identity
   before its code runs, host interpreter/dependencies, and all sandbox bind,
   interpreter/library/plugin identities. Prove no FD reuse redirection or leaked
   host handles. Removing required access must produce failure, never alternate
   loading, source-path fallback or a partial successful result.
4. **Single-generation functional gate:** only after transport passes, capture
   the bounded exact inventory and compare independently known protocol pixels.
   Check special-bit/attribute attempts cannot change credentials, capabilities
   or loader selection. Preserve deadlines, scope limits and cleanup-failure
   precedence; injected launch/read/mount failures must release unpublished
   resources and reap all descendants before leases release.
5. **Lifecycle gate:** at most ten deterministic acquire/refresh/retire cycles
   before considering any larger suite. Cover held old leases, failed refresh
   without stale fallback, permission failures, cancellation and owner teardown;
   count descriptors, backing bytes and scopes against the stated limits. Stop
   on leak, unbounded wait or identity mismatch. Performance measurement and
   broader acceptance are separate later decisions.

Review verification: read current validator/launcher/gate code and preserved
`provenance.json`/`results.json`; cross-check versioned primary sources; review
both design documents and run whitespace checks. No probe, native launch,
lifecycle test, build or package test was run for this documentation review.

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
| Invalid generation then recovery | All joined callers receive failure without ready cache entry; a later explicit refresh validates the corrected source and subsequent acquisition returns independently known pixels |
| Relocation | New explicit relocated prefix, including spaces, validates; identity excludes prefix; active old leases survive source removal from immutable backing only |
| Cancellation and owner teardown | Cancel one waiter without harming others; last-waiter cancellation frees unpublished storage; cancel at publication/launch/reply barriers; lease survives until cleanup/reaping and no cancelled result leaks |
| Retirement and resource exhaustion | Hold old in-flight leases across repeated refresh; enforce generation/byte/FD/waiter caps, including failed builds; release after drain; refusal does not corrupt the active generation |
| Sandbox and cleanup regressions | Per-operation namespaces, minimal environment, mount allowlist, limits, readiness gate, timeout, descendant cleanup and cleanup-failure precedence remain intact; bounded resources after many acquire/release cycles |

Before a go decision, demonstrate an immutable storage/namespace mechanism on the
supported host, an end-to-end launch transport including the gate and enforceable
bounds/cancellation under the approved explicit-refresh contract. Then run the
focused installed/relocated and runtime acceptance appropriate to those changes.
Do not introduce session reuse or prestarted workers. Historical feasibility
verification was the private host-native storage probe; this contract review
reuses that evidence and adds source/document review and whitespace checks only.
Provider CTest and installed-package execution are deferred because the
storage prerequisite failed and no production executable or installation behavior
changed.
