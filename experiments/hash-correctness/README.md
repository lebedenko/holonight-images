# Private bounded hash correctness experiment

Compares the installed Qt device-hashing overload with the single 65,536-byte
candidate in `candidate.h`. This is correctness tooling, with no timing or
production integration. It does not execute runtime payloads.

From the umbrella root:

```sh
python3 holonight-images/experiments/hash-correctness/test_runner.py
python3 holonight-images/experiments/hash-correctness/run.py \
  --fixture build/preview-scheduler-f2c1ty8f/B2/prefix/libexec/holonight-images/runtime \
  --preserved-inventory build/preview-scheduler-f2c1ty8f/B2/inventory.json
```

The runner creates a fresh ignored Images `build/hash-correctness-*` directory.
It first checks the installed QtCore package, SHA-256 and ELF build ID against the
reconciled provenance in the runtime-generation design. Changed identity stops
the experiment. All children, including build commands, have a 60-second deadline;
timeouts terminate the process group and reap the child, retain partial output,
and stop without automatic retry.

Device comparisons run before archiving/building validators or copying B2:

- Fourteen buffered QFile cases: sizes 0, 1 and each boundary minus/at/plus one
  for 1 KiB, 16 KiB, 64 KiB and 128 KiB, checked against Python SHA-256.
- Closed and write-only guards, requiring no reads or position advance.
- Seventy-two seekable controlled-device cases: buffered/unbuffered, permanent
  zero/negative terminal reads, both end states, at offsets minus/at/plus one
  for 1 KiB, 16 KiB and 64 KiB. Positive underlying reads are capped at 997 bytes.
- Ten borrowed-descriptor QFile faults, in dedicated children: invalidation
  before hashing and after offsets minus/at/plus one at those three boundaries.
  A QFile subclass caps the underlying read at the fault offset and closes the
  descriptor immediately after that positive read. It delegates actual reads
  and error handling to QFile. No unrelated descriptor opens intervene.

Each variant has a new device in a separate process with identical input.
Comparison covers completion, digest, final position, end and error states.
`readData()` requested/returned counts (and capped engine requests for QFile)
are diagnostics, not equality requirements or claims about syscall counts.
Full and delivered-prefix digest matches are recorded separately. Controlled
fault cases require the prefix digest and the configured end-state completion;
QFile faults record observed behavior without inventing a stricter error policy.

Only after device agreement does the runner verify all 61 frozen B2 inventory
entries, archive Images HEAD once and build baseline/candidate validation-only
executables against host dependencies. The exact-match candidate overlay adds
one private include and replaces only `hash.addData(&file)`. The open guard,
full digest comparison and other checks retain their original predicates/order.
The harness calls internal `verifyRuntime()` only. Fixture inventory and mutation
helpers are imported locally from runtime-profile; its runner is never called.

The ten runtime cases are valid, malformed manifest, duplicate path, missing
required entry, extra entry, same-size corruption, truncation, incorrect mode,
special mode and leaf symlink. Each case/variant receives its own disposable
copy, checked against the frozen inventory before mutation and inventoried
before/after validation. Copies are retained in the ignored evidence directory
for review. Frozen content is inventoried again on exit, including failure paths.
No fixtures are executed.

Evidence includes raw stdout/stderr per child, command and cleanup records,
scenario inputs and expectations, full/prefix Python digests, tooling snapshots,
source archive and overlay, compiler/dependency identities, compile commands,
binary hashes, fixture inventories and a summary. Input bytes are reproducible
from `data(size)`. Any mismatch, unexpected state, incomplete output, child
failure or fixture mutation stops qualification; the first failing scenario and
its raw observations remain available.

A passing run establishes agreement only for these finite conditions. It proves
neither universal device/error equivalence nor concurrent-mutation protection.
The descriptor fault mechanism does not simulate every filesystem failure.
Performance and production integration require separate work; generation reuse
remains no-go. See the [recorded result](../../docs/sdd/runtime-generation-reuse/DESIGN.md#bounded-hash-correctness-review-2026-11-09).
