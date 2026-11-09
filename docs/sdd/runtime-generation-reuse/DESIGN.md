# Runtime-generation reuse: design and feasibility

Date: 2026-11-09. Status: explicit-refresh contract approved; **sealed-memfd
feasibility probe stopped with no-go at the metadata immutability gate**.
Metadata contract review complete: retain exact modes; no narrowing proposed.
Static mechanism gate and portable FUSE follow-up complete: neither candidate qualifies.
FUSE daemon bootstrap remains a concrete blocker; no metadata probe is ready.
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

## Unprivileged storage static mechanism gate (2026-11-09)

**Decision: neither candidate qualifies; retain the no-go.** Private tmpfs with
read-only publication does not establish irrevocable authority removal against
the same user. A sealed read-only image served through FUSE has useful immutable
format properties, but its serving authority, metadata policy and launch transport
are unresolved. This is a static rejection of qualification, not a claim that
all possible unprivileged constructions are impossible. No narrower attacker or
mode contract, new privileged broker, system-owned runtime installation, or
process-wide consumer security changes are accepted. The search stops with these
two candidates. No candidate-specific metadata probe is justified or authorized.

### Evidence scope and host availability

Read-only inspection reused `build/runtime-memfd-feasibility-eYAKqdW8/`
`provenance.json` and `results.json`; the successful content-seal checks and failed
exact-mode check were not rerun. Current package database entries confirm Linux
`7.2.14.arch1-1`, bubblewrap `0.13.1-1`, systemd `262.1-1` and libfuse
`3.18.3-1`. `/proc/config.gz` and the installed
`/usr/lib/modules/7.2.14-arch1-1/build/.config` both report `CONFIG_USER_NS=y`,
`CONFIG_TMPFS=y`, `CONFIG_TMPFS_POSIX_ACL=y`, `CONFIG_TMPFS_XATTR=y`,
`CONFIG_FUSE_FS=y`, FUSE passthrough/io_uring enabled, and
`CONFIG_LSM="landlock,lockdown,yama,integrity,bpf"`. Configuration availability
is established; it does not establish active LSM policy or permission to mount.
The installed headers omit `fs/namespace.c` and are not a full source audit.

The review uses upstream stable **v7.2.14** sources below where retrievable,
plus matching upstream bubblewrap/systemd/libfuse tags. The Arch package's exact
patch set could not be verified: its versioned GitLab PKGBUILD was inaccessible
through the source reader. Upstream equality to the deployed kernel/tools was not established; this is
development-host provenance, not a portable acceptance requirement. FUSE device/control v7.2.14 sources were also unavailable
through that reader; the explicitly marked v7.0 device reference is only a
screening reference. SquashFUSE **0.6.1** is a versioned example, not an installed
or selected dependency. Missing exact distribution patches alone do not block
qualification. Require the semantic capabilities specified in the follow-up below;
investigate a distribution patch only when a concrete difference affects one of
those requirements. Unavailable source is not evidence of mechanism failure, and
reference source behavior is not silently promoted to a deployed-host guarantee.

`/dev/fuse`, `/usr/bin/squashfuse` and `/usr/bin/squashfuse_ll` are absent in the
sandbox view, and `/var/lib/pacman/local/squashfuse*` has no entries. However,
`/proc/self/mountinfo` shows a sandbox tmpfs mounted over `/dev`, above the host
devtmpfs. `/proc/filesystems` lists `fuse`, `fuseblk`, `fusectl`; `/proc/misc`
lists `229 fuse`; inherited mount records include `fuse.portal` and
`fuse.gvfsd-fuse`. Thus **kernel FUSE support and existing mounts are established;
host device-node availability/access is unresolved**, not disproved by sandbox
absence. `/usr/bin/fusermount3` exists with a setuid bit in this view, but that
neither proves usability nor authorizes a privileged mounting dependency. A
qualifying construction would need direct unprivileged namespace mounting; a
solution requiring a new privileged broker is excluded. No device was opened,
package installed, module loaded, permission changed or host namespace entered.

### Private tmpfs: read-only is not irreversible

The considered construction creates a user namespace U and mount namespace M,
mounts tmpfs owned by U, populates it, closes construction writers, makes the
filesystem read-only, validates, then publishes handles. Mount-local read-only
binds leave other mounts writable. Filesystem-wide `SB_RDONLY` is stronger but
reversible by its administrator. Upstream
[v7.2.14 mount code](https://raw.githubusercontent.com/gregkh/linux/v7.2.14/fs/namespace.c)
separates bind-remount flags from superblock remount authority and checks
`CAP_SYS_ADMIN` in the superblock's user namespace. Locks on mounts copied into
less-privileged namespaces do not remove authority over the original mount.

A successful non-forced read-only transition must account for existing writers;
[v7.2.14 superblock reconfiguration](https://raw.githubusercontent.com/gregkh/linux/v7.2.14/fs/super.c)
checks outstanding write access. Closing only the builder's descriptors does not
close attacker aliases or shared writable mappings acquired during construction.
Treat a failed transition as failure, never force it or publish a read-only bind
instead. Even a clean transition does not seal tmpfs against a later read-write
remount. Private propagation prevents propagation accidents, not inode mutation.

The decisive authority counterexample does not require parent-memory control.
[v7.2.14 capability evaluation](https://raw.githubusercontent.com/gregkh/linux/v7.2.14/security/commoncap.c)
grants capabilities over U to a process in U's parent namespace whose effective
UID equals U's owner. A separate same-user attacker can satisfy that condition
after the builder has dropped every capability. Given accessible namespace
handles, a single-threaded attacker with unshared filesystem state can enter U:
[v7.2.14 `userns_install` / `set_cred_user_ns`](https://raw.githubusercontent.com/gregkh/linux/v7.2.14/kernel/user_namespace.c)
checks authority in the target and installs full namespace capability sets.
The prohibition on reentering one's *current* namespace does not bar an attacker
starting in the parent. It can then satisfy M's namespace-entry checks, regain
remount authority and change bytes/modes, or overmount names used for later opens.
This contradicts the proposed inference that capability dropping freezes storage.

Accessible `/proc/<holder>/ns/{user,mnt}`, retained namespace FDs and previously
opened aliases must all be included. A normal proc denial is not a revocation of
old handles. Keeping a namespace worker non-dumpable, destroying M after transfer,
or retaining only detached mounts would require an explicit proof that no
namespace or mount authority remains reachable throughout construction and use;
none is established here. Moving the owner to another UID requires authority
outside the selected boundary. Broadly hiding the consumer's proc descriptors
would also change the existing parent security contract and legitimate access.

Ownership and security metadata are separate from mode bits: user-namespace UID/GID
mapping is not ownership by a different trusted principal. Eligible chown/chgrp,
ACL and xattr operations require their own policy. The enabled tmpfs ACL/xattr
configuration rules out assuming they are absent. Exact `0644`/`0755` does not
prove absence of file capabilities, inherited ACLs or LSM/IMA effects. Once
read-write authority returns, a read-only publication provides no durable
metadata protection. No effective pre-gate protection point is established.

### Sealed image through FUSE: immutable input is not the whole service

The alternative would construct a bounded read-only image containing the validated
inventory and exact metadata, seal its backing bytes/length before validation,
and have a trusted daemon serve only that object. Changing the backing memfd's
mode would not change the modes encoded inside the image. This is a meaningful
difference from executing a memfd inode directly, not a reversal of that no-go.

[SquashFUSE 0.6.1 operations](https://raw.githubusercontent.com/vasi/squashfuse/0.6.1/ll_main.c)
register reads/getattr/getxattr but no setattr, write or setxattr handlers;
[its stat conversion](https://raw.githubusercontent.com/vasi/squashfuse/0.6.1/stat.c)
reads modes and IDs from image metadata. Matching installed-version
[libfuse 3.18.3 dispatch](https://raw.githubusercontent.com/libfuse/libfuse/fuse-3.18.3/lib/fuse_lowlevel.c)
rejects unsupported setattr operations. These establish a read-only implementation
surface for this example, not end-to-end immunity. Image construction must reject
special bits and define IDs, ACLs, `security.capability` and security labels
explicitly; blindly copying image xattrs would preserve unwanted security effects.
Kernel permission checks, FUSE mount options and LSM policy still govern execution.

The daemon is an additional trusted parser and response producer. Its image FD,
connection endpoints, namespace handles and any transfer socket must have explicit
owners and lifetimes. Seals protect the pinned image contents even through proc
reopens, but do not authenticate FUSE replies. A duplicated *connected open file
description* is different from reopening `/proc/<daemon>/fd/N`: do not assert
that reopening `/dev/fuse` automatically joins the daemon's connection.
The older [v7.0 FUSE device code](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/fuse/dev.c)
associates connection state with file-private data and supports cloning from an
existing connected FD. Denial of connection acquisition, cloning, reply injection and retained
pre-publication aliases remains a semantic requirement. The follow-up below
restricts the proposed service to ordinary FUSE read/write transport, without
negotiated passthrough or io_uring. This review claims no demonstrated FUSE
connection exploit. A daemon-specific isolation design might help, but there is
no complete bootstrap, FD-transfer or access proof to select here; the exclusion
of hostile parent-memory control is not a blanket exclusion of attacks on a new
daemon or its proc-accessible resources.

[v7.2.14 FUSE mount code](https://raw.githubusercontent.com/gregkh/linux/v7.2.14/fs/fuse/inode.c)
binds mounts to a connection and user namespace. A sealed image does not protect
an ordinary mountpoint name against unmount/replacement. A private namespace
retains the tmpfs authority concern; pinning every leaf before publication could
avoid later pathname substitution, but its access/transport is unqualified.
Daemon termination, connection abort and unmount must fail closed without a source
fallback. They need not mutate bytes to defeat legitimate consumption; bounded
failure and cleanup, rather than resistance to all same-user denial of service,
is the requirement. Connection-control permissions are unresolved on this host.

### Legitimate object access across the launch chain

The following traces both candidates; it describes missing obligations, not an
implemented construction. Sources are current `src/isolated/runtime.cpp`,
`helper.cpp`, [systemd v262.1 scope execution](https://raw.githubusercontent.com/systemd/systemd/v262.1/src/run/run.c)
and [bubblewrap v0.13.1 setup](https://raw.githubusercontent.com/containers/bubblewrap/v0.13.1/bubblewrap.c).

| Stage | Private tmpfs | Sealed image / FUSE |
| --- | --- | --- |
| Owner before QProcess | Builder in U/M retains mount and file handles; parent needs a transferred root or individual leaf FDs. Host source path cannot name a private mount. | Daemon retains image and connection FDs; parent needs pinned served objects, not merely the image FD or a replaceable mountpoint path. |
| QProcess → systemd scope | Current QProcess closes FDs ≥3; no generation FD survives by inheritance. Parent-proc paths require parent-held stable FDs and proc permission. | Same constraint. The daemon must outlive the scope; its descriptors are not automatically passed to the launcher. |
| Scope → unsandboxed gate | Scope execution uses `execvpe` in systemd-run; it does not enter the builder's M. Gate must resolve a pinned helper via a proven proc path or redesigned FD transport. | Gate must execute the pinned served helper, not the image and not a remountable public pathname. Ordinary FUSE access as the mount owner does not prove namespace-transition access. |
| Gate → bubblewrap | Gate waits for G then `execv`s bwrap; protection must already cover the first gate exec. Host ELF interpreter/dependencies remain trusted infrastructure. | Same pre-gate requirement; daemon/image/metadata protection must already be effective. Waiting for G cannot repair an earlier substitution. |
| Bubblewrap setup | Bwrap constructs namespaces/new root, uses the old root for source access and a temporary proc bind for FD paths, then detaches the old root. Parent-proc reachability across PID/user transitions cannot be assumed. | Same lookup obligations, plus FUSE credential/user-namespace access checks. A readable host mount is not evidence of readable bind sources after transition. |
| Sandbox interpreter/libraries/plugins | Every inventory leaf must already be bound from its pinned object. Later `/usr/...` opens must resolve those objects without construction handles or host proc exposure. | Binds pin served inodes/mounts, but reads still depend on the daemon/connection and stable replies. No image or connection FD belongs in the worker. |

Neither candidate supplies the required descriptor survival/reopen proof. Passing
FDs explicitly would require changes to the current close policy and audits of
all subsequent execs. Using parent-proc paths avoids inheritance only if both
legitimate access and same-user mutation resistance hold; neither is established.
Changing only sandbox bindings leaves the unsandboxed gate unprotected.

### Comparison and stopping decision

**Established** means the specific stated fact has evidence, **contradicted**
means the proposed guarantee has a source-level counterexample, and **unresolved**
means evidence is missing. Component facts are not whole-candidate passes.

| Required property | Private tmpfs | Sealed image / FUSE |
| --- | --- | --- |
| Immutable content | **Contradicted** for accessible U/M: remount restores write authority. **Established** distinction between mount-local and filesystem-wide RO (mount/superblock sources). | **Established** backing-byte sealing primitive (preserved probe). **Unresolved** immutable served bytes: daemon/connection binding is additional. |
| Exact modes | **Contradicted** as a durable guarantee when U/M authority can be regained. | **Established** image-derived modes and missing mutation handlers in the versioned example. **Unresolved** host serving/transport guarantee. |
| Ownership, ACLs, capabilities, labels | **Unresolved** qualified policy; ACL/xattr support is **established** by config. Reversible RO is insufficient. | **Unresolved** image encoding/ID overrides, ACL/xattr policy, effective labels and exec effects; mode preservation alone is insufficient. |
| Namespace authority and replacement | **Contradicted** capability-drop argument (commoncap/userns); inaccessible-authority construction **unresolved**. | **Unresolved** unprivileged mount ownership, pinned publication and substitution resistance; sealed storage does not protect mount names. |
| Same-user proc and old aliases | **Contradicted** reliance on private names/dropped caps with accessible namespace handles. **Unresolved** complete alias elimination. | **Unresolved** connected-FD isolation and old aliases; image proc reopens preserve sealed bytes, but do not prove serving isolation. |
| Legitimate launch access, including gate | **Unresolved** transfer/reopen and namespace traversal at each stage above. | **Unresolved** same transport plus FUSE credential checks and daemon availability. |
| Dependencies/version match | **Established** development-host tmpfs/userns config; deployment policy must permit required operations. | **Established** development-host kernel support/libfuse package; **unresolved** device access and adapted image/mount tooling. Exact distribution patch identity is not a requirement. No new privileged helper accepted. |
| Resources and lifetime | **Unresolved** bounded setup/cleanup: tmpfs pages, inode metadata, writers, mount/ns/file FDs and any keeper must fit generation caps. | **Unresolved** image plus decoded page cache, daemon RSS/decompression caches, connection queues, FDs and mount lifetime; compressed size is not a memory bound. |

A tmpfs lease would have to retain its pinned mounts/files until terminal operation
cleanup, then release all handles and reap any keeper. FUSE additionally needs
the daemon alive until the last read/mapping is gone, followed by bounded unmount,
connection shutdown, child reaping and image release. Failed construction needs
the same accounting without publication. Neither has a qualified teardown that
fits the existing generation limits/deadlines; operation scopes do not account
for an owner-lived daemon. No teardown sequence is presented as executable.

The static stop gate therefore remains closed. There is **no selected construction
or publication sequence and no candidate ready for a metadata-only probe**. The
prior ordered experiment gates remain conditional requirements only; they do not
authorize proceeding on this result. Any later qualifying specification must cover
permission removal/addition, X and special bits, eligible ownership changes,
ACL/xattr operations, proc and old aliases, namespace entry/remount, legitimate
access to the same published objects, exact metadata/content identity, bounded
failure, reaping and complete descriptor/storage cleanup. Unauthorized mutation,
unexplained security effects or broken legitimate access must stop immediately.

Acquisition source modes and inventory checks, location-independent content
identity and approved explicit-refresh ordering remain unchanged. Verification
for this gate was read-only code/config/package/evidence inspection, versioned
primary-source review, document consistency review and whitespace checks only.
No builds, tests, probe reruns, mounts, native launches, lifecycle experiments,
deployment, commits or submodule updates were performed.

## Portable FUSE qualification follow-up (2026-11-09)

**Decision: stop this candidate at static qualification; retain no-go.** This is
one assessment of SquashFUSE 0.6.1 adapted to serve a sealed image through a
dedicated unprivileged daemon, with every served leaf pinned by the parent.
It does not reopen the storage search. The proposed ordering below exposes the
blockers; it is not an approved construction or an executable probe plan.

### Contract and evidence boundary

Decoder containment limits what a compromised image helper can do after entering
bubblewrap. Runtime replacement protection must also hold against an independent
same-user process before the unsandboxed gate executes, throughout construction,
and while any lease exists. The new FUSE daemon is trusted code whose protection
must be established; attacks on its memory, proc entries and descriptors are not
excluded by the existing exclusion of hostile parent-memory control. Same-user
signals, connection abort and resource exhaustion may cause bounded failure;
they may never cause substituted successful execution or source-path fallback.

Portable support requires Linux content seals, unprivileged user/mount namespace
creation and UID/GID mapping, accessible `/dev/fuse`, direct namespace mounting
of `fuse`, ordinary FUSE request/reply transport, immutable served metadata, and
proc/descriptor access compatible with the entire launcher chain. Require
`default_permissions`, `nosuid`, `nodev`, executable regular files, private mount
propagation, and no negotiated passthrough, io_uring or writable backing service.
Required mount capabilities are `CAP_SYS_ADMIN` in the new mount namespace's
owning user namespace, not host-root privilege. LSM policy must permit legitimate
execution without unexpected privilege or label transitions. Unsupported policy
fails closed. No setuid mounting helper or new broker is selected.

The earlier package/config observations are development-host evidence only.
Upstream source demonstrates mechanisms and counterexamples, not a mandatory
kernel release or distribution. A source fetch failure (including the image
reader's `fs.c`/`file.c` in this follow-up) leaves the affected trace incomplete;
it is not a failed syscall. Neither unavailable exact patches nor absence of
`/dev/fuse` in this sandbox disqualifies portable FUSE by itself.

### 1. Daemon bootstrap, credentials and connection authority

The concrete starting sequence would capture and seal the image in the trusted
parent, start a dedicated child, protect that child, give it the sealed image,
create U/M, directly mount FUSE, open every served leaf, transfer those leaf FDs
to the parent, validate through them, then publish. Only the daemon would retain
the image and connected `/dev/fuse` open file description; the parent would keep
served-file FDs and bounded lifecycle/control handles, never the connection FD.
The child would retain the caller's host UID/GID, map only those IDs into U,
deny supplementary-group changes for the mapping, and drop namespace capabilities
after setup. Neither UID 0 inside U nor a capability drop creates another trusted
host principal.

This sequence has two concrete protection failures:

- **Daemon in U:** non-dumpability alone is insufficient. A same-UID process in
  U's parent namespace has capabilities in U, including `CAP_SYS_PTRACE`.
  Ptrace's non-dumpable check permits that capability. Additional LSM denial is
  not implied by private mount propagation or capability dropping. This follows
  from [user-namespace capability rules](https://man7.org/linux/man-pages/man7/user_namespaces.7.html)
  and [ptrace access checks](https://man7.org/linux/man-pages/man2/ptrace.2.html).
  Namespace entry is not needed to gain this authority over the daemon.
- **Daemon retained in the original user namespace:** setting
  `PR_SET_DUMPABLE=0` there can deny later ordinary same-user ptrace/proc access,
  but only after that instruction. A normal child startup from a dumpable parent
  leaves an earlier attach window; ordinary exec also resets dumpability.
  Calling prctl in `main`, before opening the connection, does not prove the
  child's code was not already modified to leak it or forge replies. See
  [dumpability](https://man7.org/linux/man-pages/man2/PR_SET_DUMPABLE.2const.html)
  and [exec attributes](https://man7.org/linux/man-pages/man2/execve.2.html).
  This is a counterexample on permitted systems allowing same-user attach, not
  a claim that this development host was exploited. A protected-from-birth spawn
  or independently enforced access policy is missing. Temporarily hardening the
  parent, requiring stronger host policy, or excluding daemon attacks cannot be
  silently added to this contract.

Separating an original-namespace daemon from a mount child does not settle this:
the mount child still receives connection authority during setup, and needs the
same no-alias proof. A proposed transfer would use a precreated private socketpair,
`SCM_RIGHTS`, bounded message/FD counts, an expected child identity and generation
nonce, rejecting all unexpected messages. Same UID or a filesystem socket name
alone cannot authenticate a peer against this attacker. Even identity checks do
not authenticate a compromised expected child. Endpoint and connection duplicates
obtained earlier must be excluded, not merely closed in cooperating processes.

[The FUSE device implementation](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/fuse/dev.c)
associates requests/replies with connected file-private state and supports clone
from an existing connected FD. Reopening the device through proc is not itself
proof of joining that connection. Conversely, an actual duplicated connected
open file description is serving authority. No such FD may pass through an
unprotected process or remain in an inherited socket queue. Proc denial does not
revoke existing aliases. **Daemon-local protection as proposed is contradicted;
a complete protected bootstrap remains unresolved under the allowed boundary.**

### 2. Served content and security metadata

The sealed image is input to a parser, not a kernel-authenticated response stream.
[SquashFUSE reads](https://raw.githubusercontent.com/vasi/squashfuse/0.6.1/ll.c)
use a decoded inode in the open handle, call `sqfs_read_range`, and return a
buffer with `fuse_reply_buf`; getattr uses the image inode's stat conversion.
The trace establishes where trusted userspace replies enter FUSE. The full
bounded decompressor/cache trace is incomplete. A compromised daemon could reply
with different bytes or attributes while the image seals remain intact.

The required adaptation must take an already sealed FD rather than reopen a
mutable image name; reject unsupported image features, links, special files and
extra inventory; preserve source-mode validation and encode exact 0644/0755 files;
and encode fixed mapped UID/GID values without CLI ownership overrides.
[Stat conversion](https://raw.githubusercontent.com/vasi/squashfuse/0.6.1/stat.c)
otherwise permits UID/GID overrides. Kernel FUSE converts reply IDs in the
connection's user namespace, so validation must compare resulting host IDs as
well as image IDs. Directory metadata must be fixed and bounded too.

Define this candidate's image policy as **no xattrs**: no access/default ACLs,
`security.capability`, image-supplied security/IMA labels, or opaque user/trusted
attributes. The builder must omit them, the frozen-image validator reject them,
and the adapted daemon suppress xattr enumeration and return absence for reads;
all mutation requests must fail. Do not negotiate POSIX ACL support. This is a
required adaptation, not behavior claimed for stock SquashFUSE, which registers
xattr readers. Kernel/LSM-generated labels and mount policy remain separate:
absence of image labels does not establish absence of execution effects.

Before publishing or executing the gate, validation must cover the entire served
inventory's bytes, types, sizes, exact modes, mapped ownership and security policy
through the same pinned objects that launch will use. `nosuid` is defense in depth,
not a replacement for rejecting special bits or capabilities. The gate's host
loader/dependencies remain the already trusted host base. **Read-only handlers
and image-derived metadata are established component facts; immutable responses
and pre-gate security policy enforcement are unresolved.**

### 3. Namespace authority and pinned publication

Assume the attacker can obtain U/M handles, including old aliases, enter the
namespaces with the required setns prerequisites, remount and replace mountpoint
names. The tmpfs authority finding remains valid. For FUSE, removing a read-only
mount flag does not add write/setattr handlers to an honest daemon. A pinned leaf
FD retains its original mount/dentry; subsequent overmounts do not redirect that
object. Pinning only the root and resolving child names later is insufficient.

Every leaf must be opened before publication and validated after transfer; the
parent must retain the FDs without number reuse until all leases drain. Reopen
only those proc FD links, never the public mountpoint. This establishes the
object-pinning argument against later pathname replacement, conditional on
correct initial acquisition and transport. It does not prevent forged daemon
responses, malicious initial transfers, connection abort, or changes to effective
mount access flags. Remount authority is not automatically a connection FD, but
the bootstrap above fails to isolate the latter. **The pinning primitive is
established; complete namespace/connection substitution resistance is unresolved.**

### 4. Legitimate access without changing descriptor closing

The selected transport proposal is parent-proc reopening, preserving the existing
QProcess policy that closes FDs from 3 upward. No inheritance is claimed:

| Step | Required access and remaining obligation |
| --- | --- |
| Parent → QProcess → systemd scope | Parent keeps each leaf FD alive. Arguments contain `/proc/<parent-pid>/fd/<leaf-fd>`. QProcess closes child copies; systemd-run's scope exec must retain the argument and the PID/proc view needed to resolve it. |
| Scope → gate | Exec the pinned helper proc path; verify access with actual launcher credentials before claiming qualification. Gate ELF interpreter and host dependencies remain trusted host paths. No lookup of the runtime source tree is allowed. |
| Gate → bubblewrap | Gate passes the pinned source paths and waits for G as today. Its exec of bwrap supplies no generation FD. Protection must already have held at gate exec. |
| Bubblewrap setup | Each source must reopen the parent-held leaf through the old-root/proc view while bwrap changes user, mount and PID namespaces. A namespace transition must not make proc or FUSE permission checks fail. |
| Interpreter, libraries, plugins | Bind every leaf to its manifest destination before detaching the old root; subsequent sandbox opens resolve those bind mounts. Worker receives neither image nor connection nor parent control sockets. Reads and faults still require the daemon. |

[Kernel FUSE access checks](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/fuse/dir.c)
compare mount-owner credentials when `allow_other` is off; `allow_other` instead
checks membership in the connection user namespace or its descendants. It is
not a blanket fix for an ancestor-namespace parent. Same mapped numeric UID alone
is not a transport proof. Exact real/effective/saved IDs and namespace context at
each reopen matter. Parent-proc reopening avoids changing parent security, but
also lets attackers obtain served-file aliases: rejecting their mutations must
be an inode/service property. **Existing inheritance is contradicted by current
code; the proposed reopening chain remains unresolved.** No transport change is
implemented, and a mountpoint-path fallback is forbidden.

### 5. Mount dependencies, bounds and teardown

[Kernel FUSE registration](https://raw.githubusercontent.com/torvalds/linux/v7.0/fs/fuse/inode.c)
permits user-namespace mounting (`FS_USERNS_MOUNT`). A prospective direct path
opens accessible `/dev/fuse`, creates U/M with the caller's ID mapping, and mounts
`fuse` using that connection FD and explicit root mode/user/group options. This
requires namespace-local mount authority and host policy/device access, not a
new privileged helper. The primitive is established; the protected mount/transfer
implementation is not. Stock SquashFUSE is not a drop-in solution: its
[entry point](https://raw.githubusercontent.com/vasi/squashfuse/0.6.1/ll_main.c)
uses libfuse setup and can invoke fusermount3 on shutdown. An adaptation must
replace mount/daemonization/shutdown handling, retain parent reaping ownership,
and disable idle unmount while leases exist. It also needs a bounded image writer
and FD-based reader; neither is supplied or installed by this assessment.

The 128-file, 128-MiB payload and 256-FD caps remain unchanged, with at most one
active, one retired and one building generation. Count descriptors across parent,
daemon, mount child, transfer queues and temporary copies, not just the parent's
final leaf table. Account separately for encoded image storage (including metadata),
uncompressed payload pages, daemon executable/RSS, decompression caches, request
buffers, kernel page/inode caches and FUSE queues. Image compression does not bound
these. The current 384-MiB aggregate is a payload ceiling, not an all-in memory
allowance; the per-operation 2-GiB scope does not contain an owner-lived daemon.
No enforceable aggregate overhead budget or bounded request/cache configuration
has been demonstrated. The reference read handler allocates per-request buffers;
thread/request concurrency and attacker-generated reads also need bounds.

Required lifetime order is: reserve resources before construction; abandon and
reap on setup failure without publishing; retain daemon/image/leaf handles through
all lease terminal cleanup; on retirement admit no new leases; after drain close
leaf/bind users, detach/unmount in the owning namespace, terminate the connection,
stop and reap daemon/mount children, close control/namespace/image FDs and verify
storage release. Failure or daemon death revokes new acquisitions and fails live
operations without fallback. A stuck request requires bounded abort and cleanup;
SIGSTOP, queued work and lingering mappings must not make shutdown indefinite.
Lazy unmount alone does not release these resources. The proposed 15-second setup
and existing five-second operation cleanup budgets are not proofs of daemon
shutdown/reaping bounds. **Dependencies and lifetime are unresolved as a whole.**

### Obligation decisions and stopping point

| Obligation | Classification | Decisive evidence or missing proof |
| --- | --- | --- |
| Daemon/connection protection | **Contradicted** for daemon-local non-dumpability as sufficient; protected bootstrap **unresolved** | Namespace-owner ptrace authority; pre-protection child startup; old connection/socket aliases are not revoked. |
| Immutable served objects | **Unresolved** | Seals and read-only handlers established; trusted replies, adapted metadata policy and effective pre-gate labels not established. |
| Namespace authority/substitution | **Unresolved** overall | Leaf pinning defeats later name replacement; initial transfer, serving authority and effective mount policy remain open. |
| Legitimate launch access | **Unresolved** | Existing FD inheritance contradicted; proc reopening across the full launch chain not established. |
| Dependencies/lifetime | **Unresolved** | Unprivileged mount primitive established; protected direct mount path, bounded overhead/I/O and complete teardown missing. |

This is a specific stop on the proposed construction, not a proof that every
FUSE design is impossible. Resolving daemon bootstrap without changing the parent
security contract is prerequisite to spending effort on the remaining adaptation,
access and resource obligations. Missing distribution sources are not the reason
for this decision. No exact publication sequence qualifies and no metadata-only
probe is ready or authorized. The previously listed mutation/alias/access/cleanup
acceptance cases remain conditional; do not launch them on this static result.
The sealed-memfd no-go, tmpfs authority finding, exact-mode contract and explicit
refresh ordering are unchanged. Verification is source/evidence review, document
consistency review and whitespace checks only, with no native experiment.

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

## Full per-operation validation profile (2026-11-09)

**Retain the existing validator unchanged. This investigation did not establish a
worthwhile optimization preserving every check. Generation reuse remains no-go.**
The bounded run identifies the dominant cost, but does not qualify a faster
implementation or a storage mechanism.

Private tooling is in [`experiments/runtime-profile`](../../../experiments/runtime-profile/README.md).
Evidence is in ignored Images `build/runtime-profile-nodkmzws/`: identical archived
source, private baseline/instrumented builds, overlay patches, compiler commands,
provenance, raw wire/parsed observations, before/after inventories, child cleanup
records, `summary.json` and `verification.json`. Images source revision is
`c4db68c42207a43cffc71c80189278433950a13f`. Both builds use host GCC 16.2.1,
Qt Core/Gui 6.12.0 and Release `-O3 -DNDEBUG -std=gnu++23` on Linux
7.2.14-arch1-1 x86_64. Binary SHA-256 values are:

- Baseline: `68503399d90b07a3f0155a7ab4f40110c29dbdfbc79d440843a338125c3550d3`.
- Instrumented: `8b991d0861f4a7f1a189c86ce9f594d46ef9f839640ff8454d82b4e2da1dd32b`.

The preserved B2 runtime's 60 payloads (87,198,752 bytes) plus manifest matched
its preserved inventory before copying. Fresh disposable copies preserved modes;
no frozen payload was executed or modified. Both variants called the existing
internal `verifyRuntime()` only, without launching decoders, scopes or sandboxes.
The overlay adds buffered timing boundaries while preserving validation predicates,
short-circuit ordering, required entries and inventory traversal. Production
sources and public APIs are unchanged.

All ten correctness cases agreed with expected results in both variants: valid
accepted; malformed manifest, duplicate path, missing required entry, extra entry,
same-size byte corruption, truncation, incorrect mode, special mode and substituted
leaf symlink rejected. Each case used a separate disposable fixture so faults did
not carry into subsequent cases. Seven focused accounting tests passed before
native measurement, covering missing/truncated telemetry, rejection, phase
coverage, descriptor leaks, timeout/reaping and overhead classification.

Five warm-ups per variant were excluded. Then 100 validations per variant ran
sequentially in alternating-order pairs, with one persistent process per variant.
Startup and telemetry serialization are outside validation timing. Each harness
was bounded to 60 seconds, with no retry or experiment expansion. There were no
failures, rejected measured calls or missing observations. These are warm-cache
measurements, not cold-storage or whole-preview results.

| Observation | Samples | Median (ms) | P95 (ms, nearest rank) |
| --- | ---: | ---: | ---: |
| Baseline total | 100 | 42.457153 | 42.886367 |
| Instrumented total | 100 | 42.759970 | 43.195639 |
| Manifest load/parse and initial checks | 100 | 0.047801 | 0.056036 |
| Record/metadata checks and loop bookkeeping | 100 | 0.326227 | 0.351426 |
| File open and QFile/hash construction | 100 | 1.345922 | 1.390914 |
| Combined read/hash and digest comparison | 100 | 40.893586 | 41.284570 |
| Bind-list construction | 100 | 0.013407 | 0.015676 |
| Required-entry checks | 100 | 0.000608 | 0.000780 |
| Inventory traversal and final local cleanup | 100 | 0.127224 | 0.141107 |

Instrumented median total is **0.713% higher** than baseline, within the 10%
material-perturbation gate. Median per-sample phase coverage is **99.973%**;
recorder bookkeeping and outer call overhead account for the unassigned interval.
Baseline phase observations remain missing, not zero. The raw report retains
per-file bytes and timings: each of the 60 files has 100 open/read-hash/finish
observations. Descriptor counts remained five before and after every call.
All four correctness/measurement harness children were terminated and reaped with
no trailing telemetry. Frozen and copied inventories matched afterward.

The combined read/hash interval is **95.610% of instrumented total** at the median
of per-call fractions. The largest individual interval is the 33,112,920-byte
`libicudata.so.78`, with a 15.339065-ms median combined read/hash duration. This
supports attribution to processing payload bytes, but `addData(QIODevice*)`
combines reading and hashing; it does not isolate I/O, SHA-256 computation or a
specific avoidable inefficiency. Open timing also includes object construction.
Metadata includes loop/destructor bookkeeping. No phase is a pure syscall cost.

This single host/fixture run does not establish cold-cache behavior, concurrency,
a race defense, or end-to-end savings. No new phase timing is subtracted from the
historical **47.1106485-ms** Experiment 0 median, which remains intact. Medians
are not additive, and the earlier workload and this validation-only harness are
different experiments. The **single next-step recommendation is to retain full
per-operation validation unchanged**: no measured cost here maps to a demonstrated
worthwhile change preserving manifest, inventory, modes, size and SHA-256 checks.
No caching, skipped hashes, weaker metadata, storage search, parent-security or
freshness changes are proposed. Verification comprised focused tool tests, private
native builds, agreement checks, bounded measurements, evidence review and whitespace
checks; the full preview matrix and installed-package suite were not rerun because
production and installation behavior did not change. No deployment, publication,
commit or pin update was performed.
