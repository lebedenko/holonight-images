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


## Ranked follow-up results (2026-11-09)

**No qualified attribution**: four overhead gates exceeded 1.10 despite complete
qualification and measurement. Source decode failed block 1 p95 (1.2746), block 3
median (1.1055), and pooled p95 (1.1207); cached PNG decode failed block 2 p95
(1.2056). Inspection passed all its gates, but the full experiment gate failed.
All rankings below are **descriptive only**, including inspection.

The observed median ranking was identical across all three operation kinds,
each block and each pool: **P0→S, X→H, L→G1, H→P2, S→L, G1→X**.
P0→S was the unique largest interval in 58/60 detailed measured calls per kind;
X→H led in the remaining two. There were no median-ranking ties. This is
consistency within these observations, not qualified causal attribution.

Qualification: 36/36 passed. Schedule: 414/414 attempted; 0 unattempted. Stop: none. Recovery attempts used: zero.

Evidence: [`build/launcher-readiness-7cv0vdaw`](../../../build/launcher-readiness-7cv0vdaw/summary.json); final integrity and cleanup checks are in `post-run-audit.json`. The original `launcher-readiness-kwx9663u` evidence remains unchanged.

### Outer-readiness overhead gates

| Kind | Block | Reference median / p95 ms | Detailed median / p95 ms | Median / p95 ratio | Gate |
| --- | --- | ---: | ---: | ---: | --- |
| inspection | 1 | 25.832766 / 40.169162 | 27.606582 / 35.514138 | 1.0687 / 0.8841 | pass |
| inspection | 2 | 28.072226 / 36.758639 | 28.257690 / 38.882467 | 1.0066 / 1.0578 | pass |
| inspection | 3 | 28.079406 / 38.386631 | 28.890323 / 36.392339 | 1.0289 / 0.9480 | pass |
| inspection | pooled | 27.575456 / 38.386631 | 28.271480 / 38.395291 | 1.0252 / 1.0002 | pass |
| source | 1 | 27.181194 / 33.107024 | 29.658783 / 42.198618 | 1.0912 / 1.2746 | fail |
| source | 2 | 27.839651 / 35.957661 | 27.339409 / 35.848296 | 0.9820 / 0.9970 | pass |
| source | 3 | 26.832603 / 38.989742 | 29.662494 / 38.786082 | 1.1055 / 0.9948 | fail |
| source | pooled | 26.994706 / 36.182546 | 28.628548 / 40.551568 | 1.0605 / 1.1207 | fail |
| cached | 1 | 26.287228 / 40.528865 | 28.121966 / 38.907365 | 1.0698 / 0.9600 | pass |
| cached | 2 | 29.903737 / 33.393688 | 27.823892 / 40.259187 | 0.9304 / 1.2056 | fail |
| cached | 3 | 30.137100 / 42.373979 | 29.541401 / 41.598350 | 0.9802 / 0.9817 | pass |
| cached | pooled | 29.204356 / 40.528865 | 28.121966 / 40.573982 | 0.9629 / 1.0011 | pass |

### Six non-overlapping intervals

Detailed measured calls only; warm-ups excluded. Rows within each kind/block are ranked by median duration. Shares and closure are calculated per call. Largest counts include ties; unique counts exclude ties. No medians are summed or subtracted.

| Kind | Block | Interval | n | Median ms | p95 ms | Median share | Largest / unique |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| inspection | 1 | S-P0 | 20 | 15.786469 | 16.157063 | 53.27% | 20 / 20 |
| inspection | 1 | H-X | 20 | 9.617209 | 13.836733 | 35.77% | 0 / 0 |
| inspection | 1 | G1-L | 20 | 3.071506 | 4.558252 | 10.52% | 0 / 0 |
| inspection | 1 | P2-H | 20 | 0.264047 | 0.425874 | 0.98% | 0 / 0 |
| inspection | 1 | L-S | 20 | 0.026962 | 0.109698 | 0.10% | 0 / 0 |
| inspection | 1 | X-G1 | 20 | 0.000438 | 0.000901 | 0.00% | 0 / 0 |
| inspection | 2 | S-P0 | 20 | 15.883546 | 21.484517 | 55.19% | 20 / 20 |
| inspection | 2 | H-X | 20 | 10.484211 | 15.025789 | 37.36% | 0 / 0 |
| inspection | 2 | G1-L | 20 | 2.463134 | 3.683875 | 8.20% | 0 / 0 |
| inspection | 2 | P2-H | 20 | 0.314543 | 0.484959 | 1.07% | 0 / 0 |
| inspection | 2 | L-S | 20 | 0.025594 | 0.085287 | 0.09% | 0 / 0 |
| inspection | 2 | X-G1 | 20 | 0.000549 | 0.001381 | 0.00% | 0 / 0 |
| inspection | 3 | S-P0 | 20 | 15.757198 | 20.999763 | 54.87% | 18 / 18 |
| inspection | 3 | H-X | 20 | 10.150213 | 15.877489 | 36.00% | 2 / 2 |
| inspection | 3 | G1-L | 20 | 2.139991 | 4.897560 | 6.24% | 0 / 0 |
| inspection | 3 | P2-H | 20 | 0.335523 | 0.435421 | 1.04% | 0 / 0 |
| inspection | 3 | L-S | 20 | 0.029999 | 0.065893 | 0.11% | 0 / 0 |
| inspection | 3 | X-G1 | 20 | 0.000634 | 0.001091 | 0.00% | 0 / 0 |
| inspection | pooled | S-P0 | 60 | 15.796586 | 21.181352 | 54.30% | 58 / 58 |
| inspection | pooled | H-X | 60 | 9.930124 | 15.025789 | 36.83% | 2 / 2 |
| inspection | pooled | G1-L | 60 | 2.483229 | 4.598840 | 8.61% | 0 / 0 |
| inspection | pooled | P2-H | 60 | 0.283762 | 0.467045 | 1.03% | 0 / 0 |
| inspection | pooled | L-S | 60 | 0.027048 | 0.104878 | 0.10% | 0 / 0 |
| inspection | pooled | X-G1 | 60 | 0.000487 | 0.001236 | 0.00% | 0 / 0 |
| source | 1 | S-P0 | 20 | 15.956124 | 21.046330 | 51.91% | 20 / 20 |
| source | 1 | H-X | 20 | 9.971438 | 14.293486 | 36.92% | 0 / 0 |
| source | 1 | G1-L | 20 | 2.862976 | 6.087007 | 10.58% | 0 / 0 |
| source | 1 | P2-H | 20 | 0.278855 | 0.428310 | 0.98% | 0 / 0 |
| source | 1 | L-S | 20 | 0.029191 | 0.045764 | 0.10% | 0 / 0 |
| source | 1 | X-G1 | 20 | 0.000504 | 0.001085 | 0.00% | 0 / 0 |
| source | 2 | S-P0 | 20 | 15.699344 | 16.476706 | 52.60% | 20 / 20 |
| source | 2 | H-X | 20 | 9.787254 | 14.844422 | 36.50% | 0 / 0 |
| source | 2 | G1-L | 20 | 2.687684 | 5.448822 | 8.65% | 0 / 0 |
| source | 2 | P2-H | 20 | 0.270309 | 0.490293 | 1.00% | 0 / 0 |
| source | 2 | L-S | 20 | 0.024857 | 0.061092 | 0.10% | 0 / 0 |
| source | 2 | X-G1 | 20 | 0.000452 | 0.002125 | 0.00% | 0 / 0 |
| source | 3 | S-P0 | 20 | 15.831736 | 21.064091 | 51.73% | 18 / 18 |
| source | 3 | H-X | 20 | 11.288829 | 15.268022 | 38.29% | 2 / 2 |
| source | 3 | G1-L | 20 | 2.742153 | 5.156426 | 8.31% | 0 / 0 |
| source | 3 | P2-H | 20 | 0.334572 | 0.433968 | 1.15% | 0 / 0 |
| source | 3 | L-S | 20 | 0.031248 | 0.152698 | 0.10% | 0 / 0 |
| source | 3 | X-G1 | 20 | 0.000457 | 0.000740 | 0.00% | 0 / 0 |
| source | pooled | S-P0 | 60 | 15.814523 | 21.046330 | 51.73% | 58 / 58 |
| source | pooled | H-X | 60 | 10.640467 | 14.976063 | 37.22% | 2 / 2 |
| source | pooled | G1-L | 60 | 2.787840 | 5.448822 | 8.75% | 0 / 0 |
| source | pooled | P2-H | 60 | 0.299007 | 0.490293 | 1.06% | 0 / 0 |
| source | pooled | L-S | 60 | 0.028259 | 0.118152 | 0.10% | 0 / 0 |
| source | pooled | X-G1 | 60 | 0.000469 | 0.001094 | 0.00% | 0 / 0 |
| cached | 1 | S-P0 | 20 | 15.741532 | 20.931005 | 52.34% | 20 / 20 |
| cached | 1 | H-X | 20 | 9.842847 | 15.124127 | 36.98% | 0 / 0 |
| cached | 1 | G1-L | 20 | 3.327077 | 5.978792 | 10.30% | 0 / 0 |
| cached | 1 | P2-H | 20 | 0.323817 | 0.522086 | 1.15% | 0 / 0 |
| cached | 1 | L-S | 20 | 0.030324 | 0.130729 | 0.10% | 0 / 0 |
| cached | 1 | X-G1 | 20 | 0.000508 | 0.000750 | 0.00% | 0 / 0 |
| cached | 2 | S-P0 | 20 | 15.746144 | 21.073392 | 49.92% | 19 / 19 |
| cached | 2 | H-X | 20 | 10.389150 | 15.717218 | 36.89% | 1 / 1 |
| cached | 2 | G1-L | 20 | 3.236295 | 6.331427 | 11.06% | 0 / 0 |
| cached | 2 | P2-H | 20 | 0.316341 | 0.492465 | 1.12% | 0 / 0 |
| cached | 2 | L-S | 20 | 0.027005 | 0.041202 | 0.09% | 0 / 0 |
| cached | 2 | X-G1 | 20 | 0.000482 | 0.000909 | 0.00% | 0 / 0 |
| cached | 3 | S-P0 | 20 | 15.881971 | 20.959797 | 52.39% | 19 / 19 |
| cached | 3 | H-X | 20 | 10.662932 | 18.369674 | 36.78% | 1 / 1 |
| cached | 3 | G1-L | 20 | 2.468649 | 4.970363 | 9.12% | 0 / 0 |
| cached | 3 | P2-H | 20 | 0.361011 | 0.504442 | 1.12% | 0 / 0 |
| cached | 3 | L-S | 20 | 0.027629 | 0.098444 | 0.09% | 0 / 0 |
| cached | 3 | X-G1 | 20 | 0.000487 | 0.001174 | 0.00% | 0 / 0 |
| cached | pooled | S-P0 | 60 | 15.779219 | 20.974674 | 52.10% | 58 / 58 |
| cached | pooled | H-X | 60 | 10.389150 | 15.803908 | 36.93% | 2 / 2 |
| cached | pooled | G1-L | 60 | 3.027904 | 5.978792 | 9.67% | 0 / 0 |
| cached | pooled | P2-H | 60 | 0.328639 | 0.522086 | 1.13% | 0 / 0 |
| cached | pooled | L-S | 60 | 0.027807 | 0.124958 | 0.09% | 0 / 0 |
| cached | pooled | X-G1 | 60 | 0.000492 | 0.000958 | 0.00% | 0 / 0 |

### Consistency

- Source inspection: P0→S is the unique median leader in all three blocks and pooled.
- Source decode: P0→S is the unique median leader in all three blocks and pooled.
- Cached PNG decode: P0→S is the unique median leader in all three blocks and pooled.

### Nested timings and actual waits

Each cell is median / p95 in ms, from the same detailed measured calls. These spans overlap the six ranked intervals and must not be added to them. Complete statistics, including wait counts, gate overlap and parent write/flush timings, remain in `summary.json`.

| Kind | Block | H→R0 | R0→R1 write | F0→F1 flush | R0→P2 | Discovery work | Actual discovery waits | Actual readiness waits |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| inspection | 1 | 0.234627 / 0.366492 | 0.003805 / 0.005872 | 0.005694 / 0.008833 | 0.027446 / 0.087677 | 0.124819 / 0.219476 | 15.176689 / 15.472453 | 12.351114 / 18.104999 |
| inspection | 2 | 0.267300 / 0.415038 | 0.004300 / 0.006606 | 0.005891 / 0.009253 | 0.045318 / 0.127552 | 0.148772 / 0.234883 | 15.294507 / 20.617590 | 13.191394 / 17.470890 |
| inspection | 3 | 0.256005 / 0.373455 | 0.004490 / 0.007882 | 0.006136 / 0.011026 | 0.042093 / 0.098835 | 0.118736 / 0.234423 | 15.225655 / 20.286483 | 13.027078 / 20.454422 |
| inspection | pooled | 0.247975 / 0.392806 | 0.004219 / 0.007144 | 0.005778 / 0.010229 | 0.040225 / 0.113647 | 0.133849 / 0.234883 | 15.229017 / 20.356837 | 12.830777 / 19.535647 |
| source | 1 | 0.231423 / 0.376395 | 0.004281 / 0.009986 | 0.005740 / 0.010485 | 0.038406 / 0.089018 | 0.154609 / 0.209630 | 15.294422 / 20.414820 | 13.347554 / 20.918948 |
| source | 2 | 0.238517 / 0.409856 | 0.003830 / 0.007146 | 0.005601 / 0.012348 | 0.028334 / 0.086980 | 0.128485 / 0.194331 | 15.188527 / 15.671239 | 12.008760 / 19.858933 |
| source | 3 | 0.282199 / 0.362144 | 0.004457 / 0.011013 | 0.006332 / 0.008966 | 0.068135 / 0.137139 | 0.163611 / 0.231742 | 15.304894 / 20.446657 | 14.245566 / 19.626978 |
| source | pooled | 0.249648 / 0.395738 | 0.003969 / 0.011013 | 0.005897 / 0.010618 | 0.035202 / 0.132264 | 0.148897 / 0.211906 | 15.270073 / 20.414820 | 13.304680 / 20.605084 |
| cached | 1 | 0.268636 / 0.432376 | 0.004713 / 0.006586 | 0.006219 / 0.011352 | 0.042690 / 0.137384 | 0.129015 / 0.201191 | 15.192981 / 20.248858 | 13.160960 / 18.480632 |
| cached | 2 | 0.250978 / 0.394766 | 0.004118 / 0.006390 | 0.005962 / 0.013347 | 0.051995 / 0.113944 | 0.152133 / 0.228251 | 15.220710 / 20.377542 | 14.209618 / 19.163405 |
| cached | 3 | 0.266452 / 0.427758 | 0.004406 / 0.011857 | 0.005989 / 0.010582 | 0.071682 / 0.122580 | 0.149937 / 0.200322 | 15.379264 / 20.444259 | 13.514588 / 22.555128 |
| cached | pooled | 0.264724 / 0.432376 | 0.004365 / 0.008547 | 0.005989 / 0.013347 | 0.050267 / 0.136907 | 0.146675 / 0.224530 | 15.246648 / 20.444259 | 13.328252 / 22.091277 |

### Provenance, cleanup, verification and limits

This newly authorized session used one attempt, with no recovery or retries.
The pre-dispatch policy allowed at most one explicit tooling-defect recovery
before any warm-up or measured slot, after proved cleanup; no recovery was
permitted after measurement began. It did not replace the original failed run.
All 36 qualification cases passed (six cases for each variant/kind), including
the corrected descendant cancellation. Each variant then completed 180 measured
calls and 27 excluded warm-ups: 20 measured and three warm-ups per kind/block,
60 measured and nine warm-ups pooled per kind. No samples were trimmed,
replaced, missing or unattempted. The four failed overhead gates are retained.

Archived Images revision `4af61053fd010ab5e3f9e40ac514ff4d9f225eea` once;
`provenance.json` records its tree/archive hash, both host-native Release builds,
compiler/dependency identities and binary/overlay hashes. Existing tooling in
the archive was overlaid with the captured snapshot and required to match its
exact file/hash/size/mode inventory before instrumentation. Extra stale files
are rejected. The descendant correction remains unchanged. Reviewed archived
runtime/helper sources match the inspected working files; all overlay anchors
passed before native execution. Full runtime validation, actual memory/swap
checks, sandbox configuration, protocol, acknowledgement ordering and
hierarchical cleanup remain in place. The existing preparation script produced
both runtime bundles; their inventories differ only in the private helper and
its manifest. No earlier evidence payload was executed.

The source and cache fixtures retain separate identities/options, expected
inspection facts and independently decoded pixel hashes. Their hashes and
160×80 dimensions match those documented for the original attempt. All 450
calls have verified hierarchical cleanup within five seconds and reaped
launchers: 407 removal proofs and 43 populated-zero proofs. Final audit found
all 450 recorded cgroup directories removed. There were no watchdog
interventions. Captured tooling, fixtures and both runtime inventories remained
unchanged. Raw/parsed records, scope identities, cleanup evidence, schedules,
policy, source inventories and command/build logs remain in the ignored attempt
directory. Nothing in the original attempt was rewritten.

The original 12 focused tests passed before edits; the extended 17-test suite
passed before native dispatch. Regressions cover existing archive tooling,
stale-file rejection, stable/changing/tied rankings, per-call shares and
closure, warm-up exclusion and qualification-gated conclusions. Changed Python
syntax and repository whitespace checks pass; formatting was reviewed against
the existing Python style (no Python formatter is configured here). The fresh
Release builds verify native compilation; no native source changed afterward.
No unrelated preview, container or installed-package suites were repeated.

P0→S includes startup and scope discovery/observation delay; it is not pure
systemd execution. X→H combines exec, bubblewrap/helper loading, static
initialization and scheduling; these are not separable with these marks.
Actual waits are elapsed waits, not CPU accounting. H→P2 includes helper
initialization and readiness receipt; write and flush spans are nested, and
flush may finish after parent receipt. This measures launcher readiness, not
image decoding latency. Shared capture overhead versus production remains
unmeasured, and failed ratio gates prevent qualified attribution. No historical
subtraction, inferred savings or optimization selection follows. Production,
public APIs, dependencies, installation, pins and previously closed optimization
directions are unchanged; generation reuse remains **no-go**. No commits or
publications were created.


## Offline paired-sample review (2026-11-09)

**Decision: retain no qualified attribution; do not repeat the broad profile or
change production based on these samples.** The review found variability within
blocks and differing tail patterns, but no demonstrated tooling defect that
explains the failed gates. A constant instrumentation surcharge, one pair order,
or uniform host drift does not describe all observations. This does not rule
out instrumentation overhead or scheduling effects; the reference records lack
the internal observations needed to distinguish them.

This review reads the retained evidence only. Reproducible analysis, all 180
measured pairs, input hashes and detailed outputs are retained separately in
[`build/launcher-readiness-review-20261109`](../../../build/launcher-readiness-review-20261109/review.json)
(`review.py`, `review.log`, `pairs.json`, `input-hashes.json`). No archived code or
payload was executed. All original samples, summaries and verdicts are unchanged.
The analysis verified 414 schedule associations and outer intervals, reconstructed
all six detailed intervals and discovery/readiness wait sums for 207 detailed
calls, then excluded all 54 warm-ups for the comparisons below. It independently
reproduced all twelve original median/p95 gate ratios and checked that hashed
inputs remained unchanged. Exploratory comparisons are not replacement gates,
significance tests, causal estimates, or retrospective qualification.

### Paired differences and order

Delta is detailed minus reference readiness **within each recorded pair**, then
aggregated. It is not the difference between distribution medians. Positive
means detailed was slower. Each block has 20 measured pairs, ten per order;
each pool has 60 pairs, thirty per order.

| Kind | Block | Median paired delta ms | Detailed slower / pairs | Reference-first median delta ms | Detailed-first median delta ms |
| --- | --- | ---: | ---: | ---: | ---: |
| inspection | 1 | 0.003 | 10 / 20 | -0.228 | 2.375 |
| inspection | 2 | 1.098 | 12 / 20 | 1.872 | -0.477 |
| inspection | 3 | -0.623 | 10 / 20 | -3.097 | 1.293 |
| inspection | pooled | 0.172 | 32 / 60 | 0.003 | 1.036 |
| source | 1 | 1.880 | 14 / 20 | 3.730 | 1.203 |
| source | 2 | 1.010 | 11 / 20 | 1.010 | 0.805 |
| source | 3 | 3.132 | 13 / 20 | 2.559 | 3.132 |
| source | pooled | 2.028 | 38 / 60 | 2.028 | 2.330 |
| cached | 1 | 0.970 | 12 / 20 | 0.950 | 1.711 |
| cached | 2 | -0.761 | 7 / 20 | -0.618 | -2.158 |
| cached | 3 | 1.049 | 11 / 20 | 2.625 | 0.103 |
| cached | pooled | 0.130 | 30 / 60 | 0.897 | -0.086 |

Source decode has a positive paired median in every block and both order groups;
its pooled paired median is +2.028 ms, with 38/60 positive differences. That is
an association worth retaining, not proof of instrument cost. Inspection and
cached decode have pooled paired medians of +0.172 and +0.130 ms. Order effects
change direction across blocks; there is no universal first/second-call penalty.
Operation kinds occur in contiguous rotated batches, so kind, host conditions
and elapsed experiment time are not independently randomized. Decoding itself
follows P2 and cannot directly be timed by this readiness measure.

### Slow tails and block drift

Nearest-rank p95 with 20 calls is the nineteenth sorted observation (the
second-largest); with 60 calls it is the fifty-seventh (fourth-largest).
The table retains the threshold and higher detailed calls for the failed p95
groups, plus the two largest detailed calls in source block 3. No observation
was removed, replaced or used to recalculate a passing gate.

| Detailed call | Kind / block | First variant | Outer ms | Paired delta ms | P0→S ms | L→G1 ms | X→H ms | Discovery waits |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| m074 | source / 1 | detailed | 42.199 | 13.445 | 21.076 | 6.361 | 14.293 | 4 |
| m082 | source / 1 | detailed | 42.940 | 14.835 | 20.872 | 2.783 | 18.634 | 4 |
| m402 | source / 3 | detailed | 38.786 | 13.957 | 21.267 | 2.692 | 14.520 | 4 |
| m393 | source / 3 | reference | 40.865 | 20.017 | 21.064 | 3.345 | 16.005 | 4 |
| m054 | source / 1 | detailed | 40.552 | 16.718 | 20.874 | 5.142 | 14.191 | 4 |
| m197 | cached / 2 | reference | 40.259 | 9.958 | 20.918 | 5.381 | 13.642 | 4 |
| m209 | cached / 2 | reference | 40.574 | 20.428 | 16.325 | 8.044 | 15.717 | 3 |

Source block 1's detailed p95/max calls m074/m082 are both detailed-first;
cached block 2's m197/m209 are both reference-first. Source pooled p95 is m054,
not a new sample. The listed source tails combine four discovery waits (about
20.3–20.6 ms total) with X→H of 14.2–18.6 ms. Cached m209 has only three discovery
waits, but L→G1 reaches 8.044 ms and X→H reaches 15.717 ms. There is no single
interval responsible for every high outer observation. These detailed spans
cannot explain paired differences because reference spans were not captured.

Reference calls also have large tails: source block 1's m076/m084 take
33.107/36.183 ms while their detailed partners are 10.428/6.367 ms faster.
Source block 3's m408/m388 take 38.990/39.800 ms while their detailed partners
are 11.459/7.639 ms faster. Cached block 2 fails p95 even though detailed is
faster in 13/20 pairs and its marginal median ratio is 0.9304. The source block 3
median failure is not merely a largest-sample issue: its paired median is
+3.132 ms and 13/20 differences are positive. Full tails from both variants,
including passing groups, remain in `review.json`.

Within-block drift is mixed. Comparing the first ten with the last ten measured
calls per variant, source block 1 reference medians rise 24.646→28.764 ms and
detailed medians rise 26.114→30.233 ms. In cached block 3, reference rises
29.188→34.138 ms while detailed falls 30.102→28.010 ms. This is compatible with
varying runtime conditions but cannot establish their cause; CPU load, scheduler
traces and actual scope-availability timestamps were not recorded. No drift
correction or sample adjustment is justified by these observations.

### Discovery work versus waits

Shares are calculated within each detailed measured call before taking medians.
The residual is calculated per call as P0→S minus discovery work and discovery
waits, and includes launcher start and code between those spans. The following
medians are separate summaries and must not be summed or subtracted.

| Kind | Discovery work median ms | Discovery waits median ms | Median wait share of P0→S | Median work share of P0→S | Other elapsed median ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| inspection | 0.134 | 15.229 | 96.14% | 0.85% | 0.448 |
| source | 0.149 | 15.270 | 96.47% | 0.97% | 0.391 |
| cached | 0.147 | 15.247 | 96.41% | 0.91% | 0.386 |

Across 180 detailed measured calls, there are 526 discovery waits. Their actual
median duration is 5.072 ms (range 5.007–5.548 ms), and all return false from
`waitForFinished(5)`. Two, three, four and five waits occur in 42, 111, 26 and
one call respectively. The retained launcher code checks `/proc/<pid>/cgroup`
for the matching unit, then waits when it is absent. The records show when
checks failed and succeeded, not when the scope became available between them.
Thus the roughly 96% wait share is **not** an estimate of removable polling
latency. Startup can progress during those waits; scheduling also contributes
to elapsed time. Discovery work itself is roughly 0.13–0.15 ms at the median.
Readiness waits overlap the gate/helper intervals and must not be added to them.

### Instrumentation review and next decision

Normal reference calls contain exactly three parent observations (P0, P2, exit)
and no child records. Detailed measured calls contain 28–44 parent observations
and 17 child records. Both use the same parent stderr-draining policy, but the
detailed child path additionally performs nonblocking setup, pipe checks,
clock/namespace probes (`stat`, `clock_getres`, opening/reading monotonic offsets),
formatting and stderr writes in both gate and sandbox helper. These probes run
on ordinary detailed measurements, not only during qualification. Their cost
and any resulting scheduling/pipe effects are not independently measured.
This is a plausible observer effect, not a newly demonstrated implementation
bug. No malformed, missing or mismatched samples were found by this review.

Accept the present attribution limit. A rerun of the unchanged broad experiment
would add no new explanatory observation and must not be used to chase passing
ratios. If further profiling is pursued, the next useful work is a **new focused
design**, before implementation or execution: distinguish scope availability
from parent discovery and give both comparison arms the same minimal parent
boundary observations. It must explain how any availability observation avoids
changing scope startup, how clock qualification remains valid if repeated child
probes are reduced, and how observer cost will be bounded. Gate release must
still follow actual memory/swap verification. Preserve full validation, sandbox
policy, protocol, acknowledgement and hierarchical cleanup. Such a design might
prove infeasible or too intrusive; do not promise removable milliseconds.

This review authorizes no new native run or production optimization. Generation
reuse, hash tuning, storage changes, session reuse and prestarted workers remain
closed. Only this review documentation and new ignored analysis artifacts were
written. Syntax, arithmetic/association assertions, source review and whitespace
checks are the relevant verification; previous native builds and tests were not
repeated. No commits or publications were created.

## Focused scope-discovery experiment plan (2026-11-09)

Status: design draft, written after committing the broad profile and offline
review. This plan does not implement instrumentation or authorize a native run.
The prior verdict remains **no qualified attribution**. The focused question is:
**how tightly can the existing observations bound the time between launcher
membership becoming visible in the intended scope and the parent discovering
it?** Scope directory creation, manager registration, launcher membership,
verified limits and helper readiness are distinct events. Only membership
visibility to the existing `/proc/<launcher-pid>/cgroup` query is targeted here.

### 1. Establish feasibility before building

Use the existing discovery reads to bracket visibility; do not add a polling
thread, D-Bus subscription, kernel tracer, child message or gate handshake.
This deliberately accepts bounded timing resolution rather than promising an
exact availability timestamp. Review the host's proc/cgroup read semantics and
the systemd-run process lifecycle against the exact archived launcher path.
Establish that a complete read can be treated as a membership observation within
its start/end bracket, and that the launcher cannot leave and re-enter the
unique target scope during discovery. Record the source basis and assumptions.
If either condition cannot be justified, stop at a feasibility report; do not
build or claim availability bounds. Kernel-event tracing would require a
separate design addressing privileges, identity matching and observer cost.

The existing `fileBytes()` returns an empty array for failed open or excessive
size, and `groupOf()` maps nonmatching and unusable input to the same empty
result. Therefore an empty result is **not** sufficient evidence of absent
membership. A private overlay must retain read completion/error information and
classify complete valid nonmatching cgroup data separately from unknown reads.
Reuse the same open/read and returned bytes; add no extra query, changed retry,
delay, limit or error behavior to the launcher. Prove this observational
addition preserves the production decision for each input. Missing, malformed,
truncated or failed reads invalidate the tight bracket; never silently classify
them as a negative membership observation.

### 2. Use two variants with common parent boundaries

Archive one revision and freeze tooling, fixture, schedule and policy before
qualification. Build fresh host-native Release variants and prepare their
runtime bundles with the existing script. The two variants differ only in
whether detailed discovery observation is enabled:

| Variant | Records during normal measured calls |
| --- | --- |
| Control | Parent P0, P1, S, L, P2 and exit, plus bounded discovery counts/read-validity flags |
| Observed | The same common records, plus start/end of each existing membership query and each existing discovery wait |

P0/P2 retain the original outer-readiness boundary. S follows the successful
membership query; L follows actual memory/swap verification. Use one parent
CLOCK_MONOTONIC clock, a fixed-size in-memory ledger and serialization only after
operation completion and cleanup. No clock identity syscalls, allocation for
logging, formatting or diagnostic writes belong in these timed observations.
Retain the existing production read allocations and logic. Qualification-only
fault diagnostics must be absent from both normal measured child paths; use
production stderr handling for normal calls. No cross-process clock alignment
or helper clock/namespace probes are needed for the parent-only calculation.
Clock resolution and monotonicity must still be checked outside timed launch.

Control and observed share the same read classification and common timestamps,
so comparisons reveal incremental query/wait instrumentation cost only. Their
shared overhead versus uninstrumented production remains unknown. This design
cannot validate the earlier six-interval attribution or split bubblewrap from
loader work. Do not compare new ratios with old runs to infer improvement.

### 3. Calculate conservative per-call bounds

Under the feasibility assumptions, let [n0,n1] bracket the last complete valid
nonmatching read and [p0,p1] bracket the first complete matching read. Retain all
prior observations as well. Let A be the transition to observable membership.
Use the conservative bracket **A in [n0,p1]**, not [n1,p0]: the membership
snapshot can occur inside either read. With S >= p1:

- Launch-to-visible-membership lies in [n0-P0, p1-P0].
- Visible-membership-to-discovery lies in [S-p1, S-n0].
- Bracket width is p1-n0; never substitute its midpoint as a measured A.

A first-query success lacks a negative bound: report it as left-censored and
use only the broad [P0,p1] interval. Any unknown read is reported explicitly and
prevents a qualified tight-bracket conclusion for that call. Do not discard or
replace it. All differences, interval closure and shares are computed per call.
Report lower and upper bounds separately with n, median, nearest-rank p95 and
maximum, as well as censored/invalid counts. A wide bound is an inconclusive
result, not evidence for a midpoint or a presumed half-poll delay.

Also report query work, wait durations/counts and remaining elapsed time per
call. Wait spans overlap startup and must never be called recoverable latency.
Even a qualified bound on observation lag is not a prediction of savings from
changing polling: a different policy could change scheduling and startup.

### 4. Freeze a smaller, inspection-only budget

Use the same independently verified 160x80 PNG and source-inspection limits,
Apply orientation and disabled metadata. Inspection is sufficient for this
launcher-path question; do not generalize the result to source or cached decode.
Preserve separate qualification from measurement:

- At most 12 qualification calls: the existing six cases for each variant.
  Success uses the normal measurement configuration with child diagnostics off.
  Fault cases may enable bounded qualification-only diagnostics. Preserve the
  complete helper-entry plus descendant condition before descendant cancellation.
- After every case passes, three blocks of three excluded warm-up pairs and
  20 measured pairs, continuously alternating control/observed order. Each
  block has ten measured pairs of each order. Prewrite every slot.
- Total maximum: **150 calls** (12 qualification, 120 measured, 18 warm-ups).
  No automatic retry, recovery attempt, sample replacement or adaptive extension.
  This is a proposed budget for a separately authorized execution.

Retain the independent 25-second watchdog, five-second emergency-cleanup bound,
expected statuses, exact inspection facts, launcher reaping and hierarchical
cleanup proof. Stop on unexpected outcome, lost evidence, invalid capture,
mutation or surviving scope. Record unknown membership reads without changing
runtime behavior; stop further measurement if they defeat the required evidence.
Preserve all attempted samples and all unattempted slots. A qualified result
requires complete observations; censoring is reported, never hidden.

### 5. Decide qualification and usefulness separately

Before interpreting bounds, require observed/control median and nearest-rank
p95 ratios <=1.10 in each block and pooled for both P0→P2 and P0→S. The second
gate prevents larger total-readiness intervals from hiding a discovery-specific
perturbation. Compare products using unrounded data and positive denominators.
All safety, completeness and integrity gates must also pass. Failure means
**no qualified scope-discovery attribution**, with descriptive evidence retained
and no new run to chase a pass. Passing only bounds incremental observer cost;
it does not establish zero shared instrumentation bias.

Report paired deltas and both pair orders without using them to override the
predeclared gates. Once gates pass, describe whether the per-call bounds are
narrow enough to answer the question; report broad or predominantly censored
bounds as inconclusive. No favorable numeric result automatically authorizes a
production optimization. A tighter bound may require a different observation
mechanism and its own feasibility decision.

### 6. Verify and retain evidence proportionally

Before native work, add focused offline tests for valid nonmatches versus read
failures, first-read success, malformed/truncated input, brackets spanning read
execution, monotonic ordering, bounds/closure, warm-up exclusion, fixed counts,
missing records, censoring and overhead-gated conclusions. Review exact overlays
against the archived source, proving unchanged validation, memory/swap checks,
sandbox policy, G/R/request/reply/A ordering, deadlines and cleanup. No new
library, public API, installation, persistent helper or dependency is needed.

Retain immutable tooling/archive hashes, fixture identities, source and runtime
inventories, native build provenance, schedules, raw/parsed records, per-call
bounds, cleanup evidence and integrity checks in a new ignored directory.
Keep both historical attempts and the offline review unchanged. Update this SDD
and linked runtime-generation/umbrella notes with the result, including a
feasibility refusal or inconclusive outcome. Reuse valid focused checks and
builds; do not run unrelated preview, container or installed-package suites.
Generation reuse and all previously closed optimization directions remain closed.

## Focused scope-discovery execution outcome (2026-11-09)

**No qualified scope-discovery attribution.** The separately authorized focused
experiment completed all **150 calls**: 12 qualification, 18 excluded warm-ups
and 120 measured inspection calls (60 per variant). Two block-level
outer-readiness overhead gates failed. No retry, recovery, replacement sample,
expanded budget or second execution occurred. The earlier broad-profile verdict
remains **no qualified attribution**; no production optimization is selected.

Evidence: [`build/scope-discovery-9zyg2nw0`](../../../build/scope-discovery-9zyg2nw0/report.md),
with [machine-readable results](../../../build/scope-discovery-9zyg2nw0/summary.json)
and [post-run audit](../../../build/scope-discovery-9zyg2nw0/post-run-audit.json).
The [private sibling tooling](../../../experiments/scope-discovery-profile/README.md)
preserves the broad profiler. Production sources, APIs, dependencies, installation
and historical evidence were not changed.

### Feasibility and implementation

The retained [feasibility review](../../../build/scope-discovery-9zyg2nw0/feasibility/feasibility.md)
uses Linux **7.2.14-arch1-1** and systemd **262.1-1-arch**. Both Arch recipes match
the cached packages' recorded recipe hashes. Installed launcher/kernel-image
payloads match the cached packages; kernel sources match the recipe-checksummed
archive, and the package patches were checked. The versioned systemd archive,
tag/commit provenance, package patch and relevant manager code are retained.
Upstream master/main were starting points, not host-source substitutes.

The proc single-record read renders membership under `css_set_lock` inside the
read bracket. The selected systemd scope path submits its own PID and execs the
gate in that process. The existing gate prevents sandbox execution until the
parent observes membership and verifies actual memory/swap limits. Feasibility
assumes **no external actor migrates the launcher during discovery**, and no
external mutation of the target path or relevant namespaces. Scope creation,
manager registration, membership visibility and limit verification are distinct.
This source review establishes conditional feasibility, not measured attribution.

Both host-native Release variants came from one archived Images revision,
`7a312293cc629a0c0c9008919725166a7fe59614`. Parent fixed storage retains common
P0/P1/S/L/P2/exit boundaries, counts and invalidity; observed alone adds ordered
query/classification/wait records. The original read, returned bytes, launcher
decision, polling interval, validation, sandbox policy, protocol and cleanup are
preserved. Unknown reads would finish cleanup and stop further dispatch.

Normal success and measurement disable child diagnostics, child clock probes,
fault arguments and stderr draining; production null-stderr handling is retained.
Qualification faults alone enable bounded diagnostics. Pre-dispatch overlay review
found that the helper target also compiles runtime.cpp; its unused parent observer
was fixed to the same setting in both variants, then affected targets and bundles
were refreshed. The final helper binaries are byte-identical. Preparation manifests
from before that correction remain in `pre-review/`; no experiment calls preceded
it. Final tooling, overlays, source/runtime inventories, policy and schedules were
frozen before dispatch.

### Acceptance gates

Ratios below are observed/control; display rounding is informational. Gates used
unrounded values with positive denominators and exact 11/10 product comparisons.
Every block and pooled median **and** nearest-rank p95 had to pass for both metrics.

| Group | Outer median | Outer p95 | Discovery median | Discovery p95 | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Block 0 | **1.113138** | 1.008549 | 0.989989 | 0.998512 | Fail |
| Block 1 | 1.050997 | **1.183387** | 0.999736 | 1.024694 | Fail |
| Block 2 | 1.011205 | 0.902765 | 0.996790 | 0.985000 | Pass |
| Pooled | 1.050611 | 1.023535 | 0.997011 | 1.009179 | Pass |

Passing pooled and discovery-specific gates does not override either block failure.
All 12 qualification cases passed, including both TERM-resistant descendant cases.
All 150 calls retained verified hierarchical cleanup and launcher reaping; maximum
reported cleanup duration was 1,023 ms. There were zero unknown reads, capture
failures, unattempted slots or final integrity errors. All 140 normal calls (138
scheduled plus two qualification successes) retained no child diagnostic stream.

### Descriptive intervals and limitations

These figures are **descriptive only**, not qualified membership-to-discovery
attribution. Each observed call uses `[n0,p1]`, never `[n1,p0]` or a midpoint.
First-read success would use `[P0,p1]` and remain included as left-censored. In this
run all 60 measured observed calls were uncensored (20 in each block); the censored
groups have n=0 and no statistics. Warm-ups are retained and excluded from summaries.

| Group | Observed n | Uncertainty median (ms) | p95 (ms) | Maximum (ms) |
| --- | ---: | ---: | ---: | ---: |
| Block 0 | 20 | 5.146431 | 5.324880 | 5.440419 |
| Block 1 | 20 | 5.147334 | 5.252179 | 5.282944 |
| Block 2 | 20 | 5.147577 | 5.281130 | 5.616598 |
| Pooled | 60 | 5.146505 | 5.291018 | 5.616598 |

Pooled endpoint statistics below summarize per-call endpoints separately; they
are not the bounds of a single median call or an estimated availability timestamp.

| Quantity | Median (ms) | p95 (ms) | Maximum (ms) |
| --- | ---: | ---: | ---: |
| Launch-to-membership lower | 10.573506 | 16.100524 | 16.201020 |
| Launch-to-membership upper | 15.687224 | 21.222052 | 21.442075 |
| Membership-to-discovery lower | 0.000018 | 0.000108 | 0.000122 |
| Membership-to-discovery upper | 5.146566 | 5.291035 | 5.616704 |
| Query work | 0.147233 | 0.259493 | 0.278818 |
| Existing discovery waits | 15.182784 | 20.544629 | 20.823455 |
| Residual discovery elapsed | 0.401193 | 0.646781 | 0.721395 |

Measured observed query counts had median 4, p95 5 and maximum 5; wait counts were
3, 4 and 4. Every per-call work/wait/residual closure was exactly zero. Full counts,
median, p95 and maximum for each block and pooled, censoring groups, raw records,
per-call bounds, paired deltas and pair-order summaries remain in the evidence.
Pair comparisons are descriptive and do not override gates. Shared instrumentation
bias versus production remains unmeasured. Wait spans are not removable latency,
and these inspection results neither generalize to decoding nor estimate savings.
No post-hoc usefulness threshold is introduced. Generation reuse and all previously
closed optimization directions remain closed.

### Verification

The existing 17 focused tests passed. Thirteen new focused tests passed, including
compiled C++ checks for read classification and unchanged launcher return values,
first-read censoring, unknown/missing/unordered records, conservative arithmetic,
closure, scheduling/order, warm-up exclusion, threshold equality/failure, partial
reporting, qualification gates, exact/stale tooling inventories, overlay anchors,
normal telemetry isolation and descendant cancellation. Python syntax, changed-C++
formatting and whitespace checks passed. Both native Release builds and runtime
preparations passed, and overlays were reviewed before execution. The post-run audit
reproduced all summary rows from retained samples and rechecked frozen integrity.
No unrelated preview, container or installed-package suite was run: this changes
only private experimental tooling and documentation, with no installed contract.
