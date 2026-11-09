# Private full-runtime validation profile

This validation-only experiment calls the existing internal `verifyRuntime()`.
It never executes runtime payloads, decoders, scopes or sandboxes. Production
sources, public APIs and installation rules are unchanged. Generation reuse
remains no-go.

From the umbrella root:

```sh
python3 holonight-images/experiments/runtime-profile/test_profile.py
python3 holonight-images/experiments/runtime-profile/profile.py \
  --fixture build/preview-scheduler-f2c1ty8f/B2/prefix/libexec/holonight-images/runtime \
  --preserved-inventory build/preview-scheduler-f2c1ty8f/B2/inventory.json
```

The runner creates a fresh ignored Images `build/runtime-profile-*` directory.
It compares the frozen fixture's 61 regular files (manifest plus 60 payloads)
with the preserved B2 inventory, copies it with modes intact, archives Images
HEAD once, and builds baseline and instrumented Release executables against
host Qt. The experiment tooling is copied into both archives; only the private
instrumented runtime source receives the recorded overlay. The source archive,
overlay patches, compiler commands, dependency versions, linked dependencies,
binary hashes, raw wire output, parsed observations and machine-readable summary
remain in that directory. Both archived tooling copies preserve the runner used.

Before timing, both variants must agree with expected acceptance/rejection for
valid, malformed-manifest, duplicate-path, missing-required-entry, extra-entry,
same-size-corruption, truncation, incorrect-mode, special-mode and substituted-leaf
symlink cases. Each case uses a separate disposable copy, removed before the next
case, so faults cannot accumulate. These checks do not establish race resistance.

Measurement uses a new persistent process per variant, five excluded warm-ups
per variant, then 100 measured validations per variant with pair order alternating.
Only one validation runs at a time. Process startup and JSON serialization are
outside the validation timer. These are **warm-cache** observations; caches are
never dropped. Each harness has a 60-second wall-clock lifetime, including time
waiting for the other variant. Errors stop the run without an automatic retry;
children are terminated and reaped, partial output is retained, and final fixture
integrity is checked. Per-call tree metadata checks detect persistent mutation;
full before/after hashes check content. This is not a concurrent-mutation detector
or an atomic snapshot guarantee. The frozen tree is only read and hashed.

Telemetry is buffered in a reserved vector until validation returns. Phase names
have these precise scopes:

- `manifest_load_parse`: root checks, manifest metadata, bounded load, parse and
  version/files-array checks.
- `record_metadata`: inventory bookkeeping, path/record checks, `lstat`, modes and
  size checks, plus loop setup and previous record object/file destruction.
- `file_open`: QFile/hash construction and opening the file.
- `read_hash`: **combined reading and SHA-256 hashing** through
  `QCryptographicHash::addData(QIODevice*)`, plus digest formatting/comparison.
  This does not separate storage I/O from hashing.
- `record_finish`: bind-list construction.
- `required_entries`: required helper/plugin membership checks.
- `inventory`: recursive tree traversal, entry checks and remaining local cleanup.

Timer boundaries exclude recorder bookkeeping from phase sums, but include it
in total validation time. Coverage is the sum of observed phase intervals divided
by that sample's total. Phases are disjoint; medians still must not be added or
subtracted to predict speedups. Per-file observations retain declared/checked byte
counts and open/read-hash/finish durations. Missing values stay null with sample
count zero; rejected calls are not accepted timing samples. P95 uses nearest rank.
If absolute instrumented median deviation exceeds 10% of baseline, detailed
attribution is marked materially perturbed and must not estimate savings.
Incomplete runs never qualify attribution.

The focused standard-library tests cover missing/truncated telemetry, rejection,
coverage, descriptor leaks, timeout cleanup and overhead classification. No full
preview matrix or installed-package suite is appropriate for these private tools.
