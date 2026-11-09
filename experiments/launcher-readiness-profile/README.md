# Private bounded launcher-readiness profile

Implements the [profiling SDD](../../docs/sdd/launcher-readiness-profile/DESIGN.md).
No production source, public API, installed package, dependency or pin changes.

From the umbrella root:

```sh
python3 holonight-images/experiments/launcher-readiness-profile/test_profile.py
python3 holonight-images/experiments/launcher-readiness-profile/run.py
```

The second command is one bounded execution, requiring host user-systemd and
bubblewrap access. It creates a unique ignored `build/launcher-readiness-*`
directory in Images. It archives HEAD once, copies the executed tooling into two
disposable source trees (overlaying existing tooling and rejecting any extra files
through an exact file/hash/mode inventory), applies exact-anchor overlays, builds Release client
and helper targets against host dependencies and prepares complete runtime
bundles with the existing preparation script. Nothing is installed. Frozen
payloads are never executed. The preserved PNG is read only after its corrected
D2 audit hash is checked; a standard-library PNG decoder independently derives
expected RGBA pixels. Cached PNG bytes are encoded before launch with no image
resizing, then decoded through the existing isolated client with the thumbnails
callback's exact tier-256 limits and Ignore orientation. Source decode uses the
file-browser raster limits, Apply orientation and a 256-pixel bound. Inspection
uses those source limits, Apply orientation and metadata disabled.

`overlay.py` is the complete private production-source change. Both variants use
the same bounded parent capture policy. `telemetry.h` records integer
CLOCK_MONOTONIC nanoseconds, with raw fixed-size nonblocking stderr writes in
children. Normal reference calls record only outer readiness; qualification
calls enable all records in both variants for transport and clock checks. No new
inherited descriptor or image-protocol field is introduced. Qualification-only
arguments select faults; normal measured calls contain none. The TERM-resistant
descendant is forked by the gate inside the scope, before exec, so bubblewrap's
own descendant termination cannot masquerade as the scope's KILL escalation.

The runner's separate process enforces the 25-second dispatch watchdog,
including validation. Emergency cleanup shares one five-second deadline across
scope KILL, harness reaping and hierarchical proof. The unit journal is written
before P0, outside readiness. Failure preserves partial records and stops;
absence of proof is never treated as successful cleanup. There are no retries.
The normal cleanup path remains the production five-second implementation.

Qualification is at most 36 calls. Measurement starts only after all pass:
three rotated blocks, three excluded warm-up pairs and 20 measured pairs per
kind/block, continuously alternating pair order. This is 180 measured and 27
warm-up calls per variant. The prewritten schedule retains unattempted slots.
Every block and pooled-by-kind median and nearest-rank p95 overhead gate must
be <=1.10. Any failure yields **no qualified attribution**, without trimming,
replacement samples or additional runs to obtain a passing result.

Evidence includes source/archive/tooling/overlay/binary hashes, source and
runtime inventories, compile/link commands, dependency identities, policy,
schedules, fixture facts and hashes, per-call stdout/stderr, raw diagnostic
streams, parsed role/operation records, cleanup reports, qualification outcomes
and machine-readable summaries. Units are nanoseconds except explicit `_ms`
fields. Interval names are endpoint differences, calculated per call. Gate and
parent overlap is reported separately; flush can return after parent receipt.
Sandbox/helper startup includes bubblewrap and dynamic loading together.
R0-to-P2 is delivery plus parent observation delay, not pure transfer time.
The common stderr-capture overhead relative to production is unmeasured.

Focused tests cover schedule counts, pairing, warm-up exclusion, statistics,
threshold boundaries, strict parsing, caps, missing/duplicate records, clock
ordering, legitimate flush/receipt races, overlaps, and partial-run reporting.
No broad preview, installed-package or container acceptance suite is relevant
to these standalone private tools. Generation reuse remains no-go; this run
selects no optimization and makes no historical speedup claim.

The follow-up report ranks S-P0, L-S, G1-L, X-G1, H-X and P2-H by median
per-call duration for each kind/block and pooled by kind. It reports n, median,
nearest-rank p95, median per-call share and largest counts (including ties and
unique wins separately). Six-interval closure is checked per call. A consistent
leader must be the same unique interval in all three blocks and the pool.
Nested initialization/write/flush timings and actual discovery/readiness waits
remain separate. Conclusions require the full qualification and overhead gates;
otherwise rankings are explicitly descriptive only.

The authorized follow-up permits one explicit recovery for a demonstrated
qualification tooling defect, only with proved cleanup and before any schedule
slot, including warm-ups. There is no automatic retry loop. The session cap is
two qualification attempts (72 calls maximum) and one 414-call schedule; failures
after measurement starts cannot be recovered. Policy and tooling are captured
before dispatch. See the SDD's ranked follow-up results for the actual outcome.
