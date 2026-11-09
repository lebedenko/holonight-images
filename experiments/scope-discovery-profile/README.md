# Private scope-discovery experiment

Parent-only sibling to the preserved broad launcher-readiness profiler. See the
[specification](../../docs/sdd/launcher-readiness-profile/DESIGN.md#focused-scope-discovery-experiment-plan-2026-11-09).
Production sources are changed only by exact-anchor overlays in disposable archive
extractions. Nothing is installed. No public API or dependency changes.

The authorized execution has at most 12 qualification calls and 138 scheduled
inspection calls: three blocks of three warm-up pairs and twenty measured pairs.
Pair order alternates continuously. No retries, recovery, or replacement samples.
Warm-ups remain in completeness checks and are excluded from timing summaries.
The runner preserves the previous fixture verification, inventories, independent
25-second watchdog and five-second emergency cleanup. The copied fault controller
requires complete helper-entry and descendant records before cancellation.
`legacy_accounting.py` supplies the reviewed diagnostic parser and ratio gate.
All executed tooling and the source archive are frozen in ignored evidence.

`python3 test_profile.py` runs offline checks. `python3 run.py` prepares two native
Release variants and bundles, without experiment dispatch. Preparation uses the
single archive retained by this execution's prerequisite feasibility review at
`build/scope-discovery-feasibility-20261109/images.tar`; it is not a general runner
for an unreviewed host or revision. Review the generated overlays before execution.
Run the frozen `tooling/run.py --execute <absolute-evidence-directory>` with
`PYTHONDONTWRITEBYTECODE=1`. Exclusive creation of the execution marker forbids a
second dispatch from that directory. The session authorization allows only one
execution, regardless of directories. Do not rerun to chase a passing gate.

Both variants record P0/P1/S/L/P2/exit and discovery counts/invalidity. Only observed
records query and existing wait brackets. Storage is fixed at 32,768 records;
overflow disqualifies. Fault diagnostics alone use bounded child stderr capture.
Normal success and measurement use production null stderr, no child records or
clock probes, and no fault arguments. Helpers use the same observer constant in
both variants, including their embedded runtime validation code. Parent clock
resolution is checked before launch. Serialization follows operation cleanup.

Read classification is conservative: one well-formed unified record, a complete
path and newline, successful read status and bounded bytes. Legacy, malformed,
truncated, oversized, deleted, suffix-ambiguous and failed reads are unknown.
The original returned bytes and groupOf decision remain unchanged. Unknown reads
finish the existing cleanup path, retain evidence and stop further dispatch.

For last nonmatch [n0,n1] and first match [p0,p1], membership lies in [n0,p1].
First-read success is left-censored with [P0,p1]. No gap-only interval or midpoint
is inferred. Results retain per-call bounds, uncertainty, work/wait totals,
residuals, closure, censoring groups, pair deltas and descriptive order summaries.
Qualification, complete evidence, cleanup, integrity and every block/pooled median
and nearest-rank p95 observed/control ratio must pass <=11/10 for both outer
readiness and discovery. Passing qualifies intervals under the feasibility
assumptions, not an exact availability timestamp or savings estimate. The prior
broad-profiler verdict and closed optimization directions remain unchanged.
