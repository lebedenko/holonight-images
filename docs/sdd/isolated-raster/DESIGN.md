# Opt-in isolated Qt raster provider

## Scope and status

This production implementation adds `HolonightImages::Isolated` and `isolated.h`.
The existing `Images` API, defaults and consumers remain unchanged. This is a
limited synchronous first-frame capability, **not full backend qualification**.
GIF playback failures and the blocked Qt source-attribution audit remain open.
SVG, linked resources, animation sessions, scheduling, caches, generations and UI
are excluded. No deployment, publication or umbrella pin updates are included.

## Contract

`IsolatedClient` takes an explicit absolute runtime bundle directory and borrows
an open readable seekable `QIODevice` for each operation. It captures from offset
zero in 64 KiB chunks, including a one-byte overflow probe; reported size and EOF
hints are not trusted. Input and transport ceilings are 256 MiB. All provider
limits remain mandatory. Devices retain ownership and open state; position is
unspecified. Observed byte capture is not an atomic snapshot. Cancellation cannot
interrupt a blocking caller-device read.

Inspection, structured metadata and decode return their existing provider types
inside an optional result alongside `RuntimeStatus`. Local capture failures retain
provider `IoFailure`/`ResourceLimit`; runtime availability, malformed transport,
timeout, cancellation and unverified cleanup have separate statuses and no result.
Cancellation wins races with delivery; cleanup failure wins over cancellation.
There is no retry, in-process fallback, pathname reopening or implicit discovery.

Each operation uses a fresh helper with the existing raster/metadata code. PNG,
JPEG, BMP, TIFF, WebP and GIF are the selected first-frame formats. Unknown formats
are rejected before provider decode. No animation-session API is exposed.

## Protocol version 1

Records are four-byte big-endian lengths followed by at most 64 KiB of JSON and
an explicitly counted byte payload. Requests contain all limits and policies.
Responses contain checked enum values, structured scalar EXIF facts, inspection
geometry and raw pixels; no encoded QImage or ICC profile is deserialized by the
parent. A fixed allowlist maps QImage formats to their storage depth, including
1-bit/indexed, 8/16-bit channels and floating-point formats. Native byte layout is
appropriate to this host-native paired helper/client; cross-host transport is not
supported. Rows use the canonical 32-bit-aligned stride with zeroed padding.
Dimensions, source/output budgets, bounds, stride, byte counts, enums, palette,
finite scalar values and multiplication arithmetic are checked before creating
owned output. Palettes, alpha/precision, resolution, offset, device pixel ratio and
text metadata are preserved. Metadata exceeding the control bound is rejected,
not truncated. Unsupported valid color spaces produce provider `Unsupported` and
no image. Untagged and exact QColorSpace equality to one of Qt's eight named spaces
are represented by validated identifiers. Pixel normalization and parent ICC
parsing are forbidden.

## Runtime and lifecycle

Preparation is explicit and host-native, using `scripts/prepare-isolated-runtime.py`.
It copies the helper, four selected Qt image plugins and their ELF dependencies to
a new directory, verifies copies and publishes with rename-no-replace. A versioned
manifest records canonical destinations, modes, sizes and SHA-256 hashes. Launch
checks exact inventory, regular files, modes, sizes and hashes. These are trusted
local artifacts; hashes detect changes, not upstream authenticity or concurrent
trusted-writer mutation. Rebuild the bundle after rebuilding the helper. No runtime
host dependency discovery occurs. Host `/usr/bin/systemd-run`, `systemctl` and
`bwrap` are trusted launcher dependencies; selected codecs exist only in the bundle.

A C++ gate starts inside a unique user systemd scope. The parent observes its cgroup
and checks `memory.max=2147483648`, `memory.swap.max=0` before releasing the gate.
Bubblewrap unshares all namespaces, clears the environment, mounts only verified
runtime files, proc/dev and private temporary storage, and makes the root read-only.
Helper readiness precedes request dispatch, distinguishing namespace/startup failure
from protocol failure. Host launcher tools receive a minimal environment with only
explicit session connection variables. No caller paths are mounted.

Requests have a 15-second deadline after launcher startup. Terminal cleanup uses a
single five-second budget: scope TERM, at most one second grace, then scope KILL.
Hierarchical `cgroup.events populated=0` or removal plus launcher reaping supplies
proof. No PID-sampling fallback is accepted. Replies are published only after this
proof, including successful decode. The client reports elapsed wall time, startup, request/transfer time and observed
scope memory peak; these include startup/verification and are not codec-only timing.

## Installation and verification

CMake opt-in is `HOLONIGHT_IMAGES_ISOLATED=ON`. Installation requires an explicitly
prepared `HOLONIGHT_IMAGES_RUNTIME_BUNDLE` matching the built helper. CMake verifies
inventory/hashes and installs every file through ordinary install rules under
`libexec/holonight-images/runtime`, recording every artifact in `install_manifest.txt`.
Umbrella ownership, collision and conservative uninstall rules are unchanged.
Runtime selection remains explicit after prefix relocation.

Focused verification comprises capture adversaries, raw protocol round trips and
malformed records, a separately configured installed consumer from a relocated
prefix, direct/isolated fixture comparison and independent expected pixels, and
host runtime fault tests (crash, partial/oversized replies, timeout, cancellation
races, TERM-resistant descendants and poisoned discovery). The umbrella test
`tests/test_install_images_runtime.py` exercises actual staging and ownership.
Namespace integration needs a user systemd manager, cgroup v2 and working unprivileged
namespaces. Container binaries are acceptance-only. Existing experimental evidence
is reused for unchanged experiments; it does not qualify this transport or runtime.

## Recorded acceptance (2026-11-08)

Host-native Release `task test:isolated -- --build-type Release --build build/isolated-release`
passes **8/8 CTest entries**, including the independently configured relocated
installed consumer, all eight orientations, resource/failure comparisons, runtime
file/mode tampering, namespace denial, timeout, cancellation races, descendant cleanup
and poisoned-environment recovery. The successful run is retained at
`build/isolated-release/runtime-3415s0su/{ctest.log,tests.log,production/,fault/}`.
The production helper waits for a final acknowledgement so the parent can sample
scope memory before exit. Inherited descriptors above stderr are explicitly closed
at launch; no caller descriptor is intentionally passed through the runtime gate.

The installed consumer records **122 decode comparisons**, **9,916 ms** total,
**9,236 ms** startup (including bundle verification), **156 ms** request processing
and pixel transfer, and **5,087,232 bytes** maximum observed cgroup-accounted scope
memory. Average startup is approximately **75.7 ms**; this tiny-fixture run does not
characterize large-image performance. These are fresh installed-runtime measurements,
not historical experiment timings. Scope memory is not client RSS and excludes the
parent's capture, verification and output allocations. There is no codec-only timer.

The actual umbrella staging/ownership/collision/conservative-uninstall regression
passes with `HOLONIGHT_IMAGES_INSTALL_BUILD=holonight-images/build/isolated-release`.
Python compilation and whitespace checks pass. The pinned container builds the
opt-in package, passes its six non-host CTest entries, stages all artifacts and
checks changed-source formatting and static analysis. Container binaries are not
deployed or used as the qualifying native runtime.

The normal `task check:integration` invocation stops at pre-existing formatter
violations in unchanged `experiments/comparison/gif-facts.h` and `qt-worker.cpp`.
Those experimental files remain untouched. Focused container results are retained
in `build/isolated-container-final/`; full ecosystem acceptance was not repeated.
The experimental GIF playback failures and blocked source-attribution audit remain
open, and this evidence does not qualify full backend migration.

### Consumer-migration provider gate

The subsequent File Browser milestone fixes the two experimental formatting
violations separately from production code. The full pinned
`task check:integration` then exposed narrow fuzz-harness lint issues (braces,
argv storage and the deliberately shared cancellation flag); these are corrected.
The gate now passes (`build/acceptance/integration-jq5iuo7r`). Native provider,
relocated installed consumer and lifecycle acceptance also pass 8/8 after adding
the prefix-relative `HolonightImages_RUNTIME_DIRECTORY` package export. The
production transport and launcher remain unchanged.

## Cleanup attribution milestone (2026-11-08)

**Diagnostics implemented; historical cause unresolved.** The two failures from
Experiment 0 remain preserved under umbrella `build/preview-experiments-ak2cd2cp`.
The diagnostic run did not reproduce them; this is not evidence that they are fixed.

The private cleanup result now carries stage (`scope-identity`, `term`, `kill`,
`hierarchical-proof`, or `launcher-reaping`), elapsed milliseconds, unit/cgroup,
last cgroup observation, proof and final launcher state. Observations distinguish
confirmed removal (`stat` ENOENT), hierarchical `populated=0`, populated,
unavailable identity, unreadable observation and malformed content. Manager
`not-found` with a reaped launcher remains the existing identity-free proof.
Unknown observations cannot supply proof. A private per-invocation operations
interface supplies manager execution, observation, launcher state/waits and
monotonic time to deterministic tests; production uses the real implementations.

Failures serialize version-1 JSON through the existing diagnostic string, with
`operation.status` (the unchanged RuntimeStatus ordinal) and `operation.message`
preserved before cleanup/cancellation precedence is applied. The optional
`cleanup` object contains the above facts and manager argument lists, start result,
error text, exit code/status, timeout and stdout/stderr. Captured streams are capped
at 4 KiB, with `...[truncated]` markers; compact UTF-8 JSON is capped at 64 KiB by
further shortening command text with an explicit `truncated: true` marker while
retaining manager outcome fields.
Detailed JSON is generated only for failure. No diagnostic-only manager calls or
cgroup polls, global logging, production environment switches, wire changes,
public signatures, status changes or translated UI changes were added.

The sequence retains the five-second cleanup budget, at most one-second TERM
grace followed by KILL when necessary, hierarchical proof and launcher reaping.
Cleanup failure still suppresses results and wins over cancellation; cancellation
wins over successful delivery. The consumer deadline remains three seconds.

A deterministic regression demonstrated that the old `contains("populated 0")`
parser accepted contradictory population records. The corrected parser requires
exactly one valid populated record. Observation errors are now distinguished from
confirmed removal rather than treating every failed existence check as removal.
Neither condition has been observed in the historical failures. The pre-correction
failure is retained as `pre-correction-regression.log`; it was produced by restoring
the old permissive predicate in the new observation boundary before running the
same regression. The corrected tests cover valid/removed/unknown/malformed scopes,
query/signal disappearance, manager start/exit/timeout/malformed results,
TERM-resistant descendants, deadline/reaping failure, cancellation, original
failure preservation and bounded JSON.

Evidence is separate from fixed B:

- Provider: `holonight-images/build/cleanup-diagnostic-20261108`, native Release,
  fresh prepared `runtime-serialization-final`; final native CTest **9/9**, including installed
  and relocated consumers and lifecycle faults. Focused cleanup/capture/protocol
  CTest **3/3**, with **11** deterministic cleanup cases. The initial sandbox
  runtime failures remain in `native-runtime.log`; native execution passes.
- Umbrella: `build/cleanup-diagnostic-20261108`; freshly installed provider and
  rebuilt File Browser, Files and chooser acceptance binaries. Focused File
  Browser isolation **5/5**, existing Files/chooser offscreen acceptance passes.
- Installed-provider probe: `tooling/cleanup-diagnostic`, using the four frozen
  fixtures in `build/preview-experiments-ak2cd2cp/measure-fivw3ih0/fixtures`.
  `native-probe.jsonl` records **1,000 cycles / 3,000 successful operations** in
  **291.613 seconds**, including inspection, source decode and cached-PNG decode.
  The first invocation supplied a relative runtime and performed no launches;
  its `sandbox-probe.jsonl` is invalid preparation evidence, not a reproduction
  run or qualifying measurement. The probe now rejects that input immediately.

The bounded probe and consumer acceptance used `runtime-final`; the final
serialization-only change shortens oversized command text while preserving command
outcomes. Its deterministic tests and the provider/runtime suite were rerun with
`runtime-serialization-final`; unchanged cleanup decisions reuse the consumer
acceptance and bounded-run evidence. The probe uses the grid raster policy
(64,000,000 pixels, 32,768 extent); all frozen fixtures also fit the pane policy.

Changed-source formatting and native static analysis are checked separately from
runtime acceptance. Host clang-tidy uses a copied compilation database with the
GCC-only `-mno-direct-extern-access` flag removed; its new trailing-comma check is
excluded for the unchanged legacy runtime initializers. No unrelated container
acceptance or latency matrix is rerun. Session optimization, runtime-generation
reuse, prestarted workers, remaining Experiment 0 measurements, deployment,
publication and pin updates remain outside this milestone.

## Experiment 0 attribution (2026-11-09)

The umbrella's [diagnostic overlay tooling](../../../../tooling/preview-benchmark/README.md#experiment-0-attribution-and-scheduler-evidence-2026-11-09)
archives Images `a772a67` into a separately named D build, with the original
File Browser/Thumbnails revisions. Production sources and interfaces remain
unchanged. Private probes correlate capture, runtime validation, launcher/readiness,
transfer, response validation, acknowledgement/exit and cleanup with consumer jobs.
Bounded helper stderr reports provider execution and reply serialization without
changing stdout framing. Provider execution includes format sniffing and provider
work, not just codec time. Parent/helper intervals remain separate; overlapping
phases are never summed. Overflow, truncation and absent observations are explicit.

Pre-acknowledgement cpu.stat/memory.peak and a separate 10 ms parent-RSS/concurrent
scope-memory pass retain resource evidence before helper exit. One-second settled
scope/process observations do not replace the hierarchical cleanup proof and do
not establish leak freedom.

The attribution pass stopped at its first cleanup failure after 216/280 samples
and 544 provider calls. The full diagnostic records a successful operation, exited
launcher, unreadable hierarchical observation, no proof, and no manager commands.
No retry or extra manager cleanup followed. This is a new observed failure stage,
not an explanation of the two historical failures. The independent resource pass
completed 84 samples and 220 operations. See the
[umbrella evidence report](../../../../docs/initiatives/image-isolation.md#experiment-0-missing-evidence-2026-11-09)
for artifacts, counts, missing observations and limitations.

Native Release provider/runtime and installed/relocated checks pass 9/9; focused
capture, protocol and cleanup checks pass 3/3. Static analysis passes on the
instrumented sources. Experiment 0 remains incomplete. Resolve the cleanup gate
before choosing an optimization; runtime-generation reuse is only a conditional
next experiment suggested by the observed validation cost. No optimization or
cleanup behavior change is included in this milestone.
