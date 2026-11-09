# Bounded launcher-readiness profile

Specification dated 2026-11-09. The user subsequently authorized private
implementation and one bounded run. See [execution results](#execution-results-2026-11-09)
for the completed attempt and its **no qualified attribution** disposition.
The design-only authorization statements below describe the original review.

## Question and scope

How much of launcher readiness falls before successful scope discovery, between
verified limits and gate consumption, during sandbox/helper startup, and between
helper readiness and parent receipt? Report **source inspection, source decode
and cached PNG decode separately**. The historical D2 readiness median was
27.226 ms overall: 27.486 ms for inspection, 27.103 ms for source decode and
26.755 ms for cached PNG decode. These are historical observations, not targets
or predictions for this new fixture and host run.

The [runtime-generation design](../runtime-generation-reuse/DESIGN.md#hash-candidate-closure-and-next-target-evidence-review-2026-11-09)
retains the historical evidence and closes the 64 KiB hash candidate without
production integration. Full per-operation validation remains unchanged;
generation reuse remains **no-go**. Hash tuning, storage mechanisms, session
reuse and prestarted workers stay closed. No public API, production source,
installation, dependency, pin or Grub changes belong to this experiment.

## Source basis and outer boundary

Reviewed current `src/isolated/runtime.cpp`, `helper.cpp` and `cleanup.cpp`, and
the preserved umbrella
`build/preview-diagnostic-ymcm3gs7/D2/source/holonight-images/src/isolated/{runtime,helper}.cpp`
and diagnostic overlay/telemetry definitions. The corrected iteration's
`build/preview-iteration-m9uucbpj/audit.json` identifies that D2 package.
All inspection is read-only; frozen sources and payloads must never be modified
or executed for this work.

D2 starts `launcher_readiness` immediately before
`process.start("/usr/bin/systemd-run", command)` and ends after successful
`receive(1) == "R"`. Current code preserves this sequence. Runtime validation
and command/environment construction precede the interval; request framing and
transfer follow it. `result.startup` is broader and must not substitute for it.
D2's `helper_launch` follows `waitForStarted(1000)`; its `scope` event follows
readiness and does not observe scope discovery. Existing records cannot split
the internal readiness contributors.

## Private variants and inputs

Archive one Images revision once, record commit/tree and archive SHA-256, and
derive both private host-native Release builds from it. Record compiler,
configuration, compile/link commands, host dependencies, launcher tools and
binary hashes. Use identical settings, command arguments, environment, limits,
protocol and launch behavior. The reference records only outer readiness;
the detailed variant adds the observations below. Keep overlays reviewable and
retain their hashes. Neither variant integrates the closed hash candidate.

Prepare disposable runtime bundles containing the corresponding newly built
private helper, with complete valid manifests, exact modes and inventories.
Preserve dependency provenance and record each helper/library identity; bundle
differences must be explained by the private instrumentation. Use the existing
runtime preparation rules, never an acceptance-only manifest exception. Validate
each operation in full, including required entries, inventory, path/regular-file,
exact-mode, size and full SHA-256 checks. Do not repoint, execute or edit frozen
evidence packages; provenance inspection is read-only. Deployment uses no
container-produced binaries and no installation step is part of this design.

Use one preserved small PNG with recorded bytes, dimensions, expected inspection
facts and exact decoded pixels. Create disposable source and cached-PNG inputs
before timing; cache input preparation/encoding and caller acquisition are outside
readiness. Record cache bytes/options separately even if identical to source.
Exercise the real cached-PNG operation route with its intended options, while
retaining fresh helpers/scopes. Fix options before qualification. This is a
serial warm-cache launch profile, not a cold-storage or consumer-cache benchmark.

## Observations and clocks

Use integer nanoseconds from `clock_gettime(CLOCK_MONOTONIC)` in every role.
Before measurement, qualify a common epoch/rate across the parent, unsandboxed
gate and sandbox helper, including time-namespace identities and offsets.
Record clock resolution and bounded parent/child handshake brackets outside the
measurement sample. Check causal ordering with those brackets; matching clock
names alone is insufficient. No wall-clock substitution, inferred offset or
post-hoc alignment is allowed. Incomparable clocks stop qualification.

| Mark | Observation point |
| --- | --- |
| P0 | Immediately before QProcess `start`, after validation and command setup |
| P1 | Immediately after successful `waitForStarted(1000)` |
| S | Immediately after `groupOf` first returns the matching scope |
| L | After actual `memory.max == 2147483648` and `memory.swap.max == 0` verification |
| W0, W1 | Before and after the parent writes `G`, including return count |
| W2, W3 | Before and after existing `waitForBytesWritten(5)`, including result |
| G0 | Gate branch entry, before its existing poll/read |
| G1 | After successful read and validation of `G` |
| X | Immediately before `execv` of bubblewrap |
| H | First observable sandbox-helper main entry, before QCoreApplication construction |
| R0, R1 | Before and after helper `output.write("R", 1)` |
| F0, F1 | Before and after helper readiness `output.flush()`, including success |
| P2 | Immediately after parent successfully receives and validates `R` |

Capture helper entry at main entry and classify gate versus sandbox role without
moving application initialization. It is not ELF entry: loader and static
initialization already happened. For each scope-discovery attempt, record start,
end and success, and before/after timestamps and result of each actual
`waitForFinished(5)`. Also bracket readiness `waitForReadyRead(5)` calls. Preserve
existing checks, wait arguments and deadlines; 5 ms is a bound, not an assumed
sleep. Record failed boundaries explicitly rather than inventing a completion.

Associate all observations with run, variant, block, operation kind, warm-up flag,
pair index, unique operation ID, role, role-local sequence and PID. Namespace PIDs
may differ or repeat: a dedicated per-operation stderr stream and its parent
launch mapping establish association. Child records can acquire the operation
ID from that mapping after capture; do not pass it through the image protocol or
weaken the cleared environment/descriptor policy. Gate and sandbox roles remain
distinct even when an exec preserves a PID.

## Record transport and bounded evidence

Use private versioned diagnostic records on stderr, separate from stdout's
unchanged `G`/`R`, framed requests/replies and `A` acknowledgement protocol.
Parent timestamps go to a bounded in-memory ledger and are serialized outside
readiness. Child records use fixed-size formatting and one bounded raw write per
record, at most 512 bytes and below the verified pipe atomic-write limit. Avoid
iostream/Qt logging initialization on this path. Gate records must be emitted
before exec: destructor flushing would lose them. X is sampled before its
record write and exec, so that residual instrumentation cost is explicitly inside
X-to-H. No new inherited descriptor is introduced; stderr survives the existing
systemd-run/gate/bubblewrap path, to be verified during qualification.

Both private variants capture stderr instead of production's null sink. Drain
available bytes without waiting for diagnostic records at existing parent wait/
check boundaries, and drain through bounded cleanup and child exit. Keep stdout
as QProcess's protocol read channel. Do not add a readiness handshake, blocking
log flush in the parent, logging thread or extra launch wait. Child diagnostic
writes must be nonblocking; a short write, EINTR or EAGAIN is a capture failure,
not a reason to retry or delay launch. Qualify that this diagnostic-only change
does not affect stdout or launcher behavior. Reference and detailed capture use
the same drain policy; report their shared overhead as unmeasured relative to
uninstrumented production.

Cap parent observations at 32,768 records and retained stderr at 256 KiB per
operation, including non-diagnostic launcher messages. Bound parsing and raw
retention independently of QProcess buffering; cap exhaustion stops the run and
initiates cleanup. Never silently wrap a ring buffer. Retain raw bytes, parsed
records, stream completion and per-role counts; require expected role trailers
or the gate's pre-exec terminal record. Duplicate, malformed, unknown-version,
missing, out-of-order or truncated diagnostic records invalidate attribution.
Retain any available outer measurement and partial evidence as unqualified.
Late stderr delivery does not move event timestamps or P2.

## Accounting without false attribution

Calculate each interval per operation before aggregating. P2-P0 is the outer
readiness measure in both variants. Report S-P0 (with P1-P0 and S-P1), L-S,
G1-L, X-G1, H-X and P2-H. The latter two include sandbox/helper startup and
helper initialization/readiness delivery respectively. Report H-to-R0,
readiness write/flush durations and P2-R0 as additional nested observations.

Gate loading/startup and G0-to-G1 may overlap parent discovery and limit checks.
W1 and W3 are parent observations, not proof of gate consumption. Neither is
required to precede G1. F1 may occur after P2 because the parent can consume the
byte before the helper timestamps flush return; do not reject that legitimate
ordering or treat a negative P2-F1 as a transfer duration. R0-to-P2 is observable
delivery plus observation delay; pure transfer, wakeup and scheduling costs are
unresolved. Readiness flush timing is a sibling interval, not an additive phase.

Use the causally ordered P0/S/L/G1/X/H/R0/P2 chain for disjoint coverage; show
other intervals as nested/overlapping spans and compute unions/intersections
per call where needed. Check closure against P2-P0 before aggregation. Never
sum overlapping spans or subtract medians. H-X combines gate emission/exec,
bubblewrap loading/setup, helper dynamic loading/static initialization and
scheduling; these observations cannot separate bubblewrap from loader work.
S-P0 similarly includes systemd startup and discovery/observation delay, not pure
systemd execution. Actual waits characterize parent waiting, not CPU use or
proof of polling dominance. No historical timing subtraction predicts savings.

## Fixed sampling budget and overhead gate

Use three serial blocks. Within each block and operation kind, run three excluded
warm-up reference/detailed pairs, then 20 measured pairs. Rotate kind order:
inspection/source decode/cached PNG, source decode/cached PNG/inspection, then
cached PNG/inspection/source decode. Alternate reference-first and detailed-first
pairs using a prewritten schedule, including warm-ups, without concurrent calls.
Each call completes validation, operation, acknowledgement and verified cleanup
before the next call. This yields **180 measured calls and 27 warm-ups per
variant** (360 measured and 54 warm-up calls total). There is no adaptive sample
size, retry, trimming or replacement of failed calls.

Retain every scheduled/attempted sample and list unattempted slots after an early
stop. Report success/failure, warm-up and missing-observation counts, median and
nearest-rank p95 (`sorted[ceil(0.95*n)]`, one-based) by kind and block and pooled
by kind across blocks. Median averages the middle two values for even counts.
Preserve pair identities even though the gates compare distribution summaries.
Do not pool kinds into a qualification gate or hide a failed block by pooling.

For each kind in each block **and pooled by kind**, require detailed/reference
outer-readiness median ratio <= **1.10** and p95 ratio <= **1.10**. Denominators
must be positive, with complete expected observations in both variants. These
are practical instrumentation-overhead gates, not significance tests or
optimization/speedup gates. Any failed gate or incomplete evidence means **no
qualified attribution**. Publish descriptive results with that verdict; do not
expand the budget to obtain a pass. Passing does not prove zero measurement bias
or generalize the result to other machines, fixtures or mixed workloads.

## Future qualification and failure handling

Before a separately authorized run, focused offline checks must cover strict
record parsing and bounded capture, role/operation association across exec,
duplicate/truncated/missing records, pair ordering, warm-up exclusion, block and
pooled counts, median/nearest-rank p95, equality at 1.10 and failures just above
it, zero denominators, causal clock ordering, legitimate F1/P2 races, overlap
unions/coverage, missing samples and early-stop reporting. No such tests run as
part of this documentation change.

Future runtime qualification is separate from measured samples: for each variant
and each kind, one successful operation, cancellation before gate release,
cancellation while awaiting readiness, readiness timeout, failed readiness and
cleanup with a TERM-resistant descendant (six cases, 36 total calls maximum).
Use private fault controls only for those cases; normal measurement has none.
Verify expected status, exact successful facts/pixels, no partial successful
publication, stderr survival/draining, role clocks and child termination/reaping.
Stop at the first unexpected qualification result; no repeated attempts. A
clock/transport handshake belongs to these qualification calls, outside samples.

Preserve fresh scopes/helpers, full validation, verified actual memory/swap limits
before G, sandbox binds/namespaces/environment and close-descriptors policy,
cancellation checks, the existing 1-second QProcess start wait, 15-second request
deadline and gate poll limit. Preserve reply validation and acknowledgement
ordering. Terminal cleanup retains the five-second total budget, at most one
second TERM grace followed by KILL where needed, launcher reaping and hierarchical
`cgroup.events populated=0` or removal proof (or the existing verified manager
not-found path before scope discovery). PID absence alone is insufficient.

A private independent watchdog must bound each call to 25 seconds from dispatch,
then allow at most five seconds for emergency termination/reaping and scope proof;
it must cover validation and a hung harness as well as launcher startup. Record
watchdog intervention as failure, preserve partial evidence and never proceed
to the next operation without cleanup proof. If proof fails, report surviving
children/scopes explicitly and stop; do not claim cleanup success.

Stop on unexpected results, clock/capture failure, surviving children/scopes,
fixture or bundle mutation, inventory mismatch or incomplete evidence. Check
input/bundle identities before qualification and after each block and at exit.
Retain policy/schedule, source/overlay/build provenance, fixtures and inventories,
raw and parsed observations, unsuccessful/partial records, statuses, scope IDs,
cleanup proof, watchdog events and summary in a unique ignored directory. No
automatic evidence regeneration, retries or budget expansion are permitted.

## Documentation verification and disposition

This specification's boundaries were reviewed against current and archived launch
code, including gate exec, readiness flush and hierarchical cleanup. Cross-links
and conclusions agree with the runtime-generation design and umbrella image
isolation note. Verification is document/source review and whitespace checks in
Images and the umbrella only: no builds, tests, benchmarks or runtime payloads.
Frozen evidence, Grub and pins remain untouched; no commits or publication.

The design is ready for separate implementation review. It does not authorize
implementation or execution, select an optimization, or change the generation
reuse no-go and hash-candidate closure.


## Execution results (2026-11-09)

Implemented the standalone [private experiment](../../../experiments/launcher-readiness-profile/README.md)
and executed one bounded attempt. **No qualified attribution**: qualification
stopped at its sixth call; measurement never began. The stop was an experiment
fault-controller race, not evidence of a production launcher failure or an
instrumentation-overhead pass/failure. There were no retries or replacement calls.

Local ignored evidence is
[`build/launcher-readiness-kwx9663u`](../../../build/launcher-readiness-kwx9663u/summary.json).
Its `tooling/` snapshot is the exact executed version; `images.tar`,
`provenance.json`, `commands.json`, per-command logs, both source inventories,
overlays, compile databases and runtime inventories preserve the build inputs.
Images HEAD was archived once at `010dc524ed9e6895370f7b341c4a8c7897fcfe04`
(tree `fe2f6082e61df80179ef51a70218129bed59e6bf`, archive SHA-256
`57761316005b7593f9e39817910d721c865cca845dc840bdfbbb52d8c26f20da`).
Both host-native Release variants built successfully with the existing isolated
client/helper targets and runtime preparation script. Runtime inventories differ
only in the private helper binary and the manifest describing it; dependency
payloads are identical.

The preserved source PNG matched corrected D2's
`610672660f509f2fc6afff14459f7c5575c5f3589c0354938d02376f9874e587`.
Independent PNG decompression/filter reconstruction established 160×80 opaque red
pixels, RGBA SHA-256
`9ca8655491d9336bbc5b89d695785de5bbea67b317efdb5eb648bf6dc4f598c0`.
Cache encoding was completed before any calls; its bytes happened to be identical
to the source, with separate files, hashes and policies retained. Source
inspection uses Apply and metadata disabled; source decode uses the file-browser
raster limits and a 256 bound; cached decode uses the thumbnails callback's exact
tier-256 limits and Ignore. Neither decode route was reached by this attempt.

### Qualification and cleanup

The six attempted calls were all reference/source-inspection qualification calls:

| Case | Result | Cleanup proof | Cleanup ms |
| --- | --- | --- | ---: |
| Success | Passed, exact inspection facts | Removed | 2 |
| Cancel before release | Passed, Cancelled and no publication | Populated zero | 9 |
| Cancel awaiting readiness | Passed, Cancelled and no publication | Removed | 13 |
| Readiness timeout | Passed, Timeout and no publication | Removed | 20 |
| Failed readiness | Passed, Unavailable and no publication | Removed | 3 |
| TERM-resistant descendant | Qualification failed: missing helper-entry H | Removed after TERM and KILL | 1021 |

The successful qualification call verified shared CLOCK_MONOTONIC observations:
parent, gate and sandbox helper reported time namespace inode `4026531834`,
1-ns resolution and zero monotonic offsets, with causal brackets and complete
streams. This establishes transport/clock behavior for that call only. It does
not qualify the unattempted variants or operation kinds. Its raw outer readiness
was 31.970671 ms, retained solely as qualification evidence, not a measurement
sample or performance distribution.

In the final call, the gate's descendant record triggered cancellation before
sandbox-helper entry. Gate G0/G1/X and the descendant record survived stderr;
H and subsequent helper records were absent. The validator rejected the fault
location. The operation returned Cancelled without a published result, TERM was
followed by KILL, and the launcher was reaped with hierarchical removal proof.
The final audit found all six cgroups removed and no remaining recorded host
children. No independent-watchdog intervention occurred. Fixture and runtime
inventories remained unchanged. Existing bounded cleanup reports retain their
explicit observation counts/truncation flags and final proof.

### Counts and unavailable distributions

Five qualification cases passed, one failed, and 30 were unattempted. One
qualification call has the unexpected missing helper-entry observation; missing
readiness completion in intentionally cancelled/failed calls is not a sample.
The fixed measurement schedule remains fully unattempted:

| Operation kind | Block(s) | Measured reference / detailed | Warm-ups reference / detailed | Missing measured slots reference / detailed | Median / p95 intervals and overhead ratios |
| --- | --- | --- | --- | --- | --- |
| Source inspection | Each of 1, 2, 3 | 0 / 0 | 0 / 0 | 20 / 20 | Unavailable |
| Source decode | Each of 1, 2, 3 | 0 / 0 | 0 / 0 | 20 / 20 | Unavailable |
| Cached PNG decode | Each of 1, 2, 3 | 0 / 0 | 0 / 0 | 20 / 20 | Unavailable |
| Source inspection | Pooled | 0 / 0 | 0 / 0 | 60 / 60 | Unavailable |
| Source decode | Pooled | 0 / 0 | 0 / 0 | 60 / 60 | Unavailable |
| Cached PNG decode | Pooled | 0 / 0 | 0 / 0 | 60 / 60 | Unavailable |

All 360 measured calls and 54 warm-ups remain unattempted (180 and 27 per
variant). No overhead ratio can be evaluated. `summary.json` preserves the
original verdict and slot list; `post-run-audit.json` adds explicit empty
statistics/counts and final integrity/cleanup checks without rewriting the run.
No historical subtraction, speedup inference or optimization selection follows.

### Post-run correction and verification

The working tooling now requires complete helper-entry **and** descendant records
before cancelling the descendant qualification case. A compiled offline regression
covers both record orders, missing entry, partial records and non-cancellation
cases. The executed snapshot is unchanged, and the correction was **not** rerun
through native qualification. Additional offline checks reject cross-role marks,
missing stream completion and omitted warm-ups. Twelve focused tests pass;
Python byte-compilation, native syntax checks of the corrected runtime/helper
and harness against the same archive, changed-C++ formatting checks and both
repository whitespace checks pass. Both original native Release builds passed.

No broad preview, container or installed-package suites ran: this change is
confined to standalone private tooling and documentation. The independent
watchdog/emergency path was implemented but was not triggered during this run;
full runtime qualification remains incomplete. Any future native run would need
separate authorization and cannot replace this failed bounded attempt.
Production/API behavior, dependencies, installation, frozen evidence, Grub and
pins remain untouched; no commits or publication. Generation reuse remains
**no-go**; hash tuning, storage mechanisms, session reuse and prestarted workers
remain closed.
