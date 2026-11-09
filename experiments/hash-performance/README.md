# Private bounded hash performance experiment

Measures full internal `verifyRuntime()` latency for the already reviewed 64 KiB
candidate. Production code, installation and generation reuse are unchanged.
The harness never executes runtime payloads. Qt `QElapsedTimer` surrounds only
the validation call; path conversion, descriptor inspection and JSON output are
outside the timer. Both Release executables use identical host dependencies,
flags and harness code from one Images HEAD archive. Only the existing exact
candidate overlay is applied, preserving the open guard and digest comparison.

Run from the umbrella root:

```sh
python3 holonight-images/experiments/hash-performance/test_runner.py
python3 holonight-images/experiments/hash-performance/run.py \
  --fixture build/preview-scheduler-f2c1ty8f/B2/prefix/libexec/holonight-images/runtime \
  --preserved-inventory build/preview-scheduler-f2c1ty8f/B2/inventory.json \
  --correctness-evidence holonight-images/build/hash-correctness-h3eyasci
```

A fresh ignored Images `build/hash-performance-*` directory retains policy,
tooling snapshots, commands, raw stdout/stderr, source archive and overlay,
source/binary hashes, compile commands, compiler/dependency and host identities,
parsed observations, expected verdicts, inventories and child cleanup records.
Missing or changed preserved correctness evidence, candidate, helper, validation
sources, B2 inventory or installed QtCore package/hash/build ID stops qualification.
The unchanged 98-case device evidence is reused; neither imported runner runs.

Before measurement, all ten existing validator cases run independently in each
variant with fresh disposable copies. Each measurement block then uses one fresh
valid copy shared by two fresh persistent processes. There are exactly three
blocks, each with five excluded warm-up pairs and 50 measured pairs (150 measured
validations per variant). Pair order alternates continuously within each block;
blocks start baseline-first, candidate-first, baseline-first. Calls are serial.
All timings are warm-cache; no cache drops, CPU setting changes, concurrent test
workloads or cold-storage claims. No retries, extra samples or outlier trimming.

Every block and the pooled result must meet all three gates:

- Median paired absolute savings at least 4 ms.
- Median paired relative savings at least 10%.
- Candidate nearest-rank p95 at most 105% of baseline p95.

Relative savings are `(baseline_ns - candidate_ns) / baseline_ns`, algebraically
`1 - candidate_ns / baseline_ns`. Reports include variant medians and p95 plus
both paired medians. Any missed gate in a complete run means **worthwhile savings
not demonstrated**. These are practical criteria, not statistical significance.

Every child has a 60-second bound, including persistent-process idle time.
Timeout/error cleanup terminates and reaps, escalating to kill when necessary,
while preserving partial output. Invalid/missing/duplicate/trailing output,
unexpected verdicts, invalid durations, descriptor leaks, process failures or
fixture mutation mean **no qualified performance result**. Metadata is checked
around each call; full inventories surround cases and blocks. Frozen integrity
is checked again on exit, including failure paths. Disposable fixtures remain as
reproducers in the evidence directory.

Focused tests run before native execution. They cover pairing/accounting,
warm-up exclusion, inclusive thresholds, inconsistent blocks, p95 regressions,
strict parsing, verdict mismatches, process failure, trailing output and timeout
cleanup with partial-output retention. No full preview or installed-package
suite is necessary for this private experiment.

Conclusions apply only to this host, B2 fixture and warm-cache full-validation
workload. They establish neither whole-preview savings, universal error
equivalence nor concurrent-mutation protection. A passing result recommends a
separate production-integration review only; generation reuse remains no-go.
