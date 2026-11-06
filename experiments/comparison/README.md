# Rust Glycin and isolated provider comparison

Private, non-installed Linux experiments. The production build never includes this
directory. The [dated decision](../../docs/sdd/glycin-feasibility/DESIGN.md) records
failed and unproven gates; successful decoding does not qualify a backend.

Run from `holonight-images`, with native host dependencies, working user namespaces,
bubblewrap, strace, Cargo/Rust, and a systemd user manager supporting cgroup-v2 memory
accounting. The Rust crate is **3.1.0**, loader protocol **2**, tested against the
installed **glycin 2.2.6-1** loaders. Cargo.lock pins the private dependency graph;
it does not change any production dependency or umbrella pin.

```sh
# Existing independent fixtures and the historical probe's fixture generator.
cmake -S experiments/glycin -B build/glycin -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build/glycin

CARGO_TARGET_DIR="$PWD/build/comparison/rust" cargo build --release --locked \
  --manifest-path experiments/comparison/rust/Cargo.toml
cmake -S experiments/comparison -B build/comparison -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DGLYCIN_BRIDGE="$PWD/build/comparison/rust/release/libcomparison_glycin_bridge.a"
cmake --build build/comparison

python3 experiments/comparison/run.py build/comparison --smoke --warmups 0 --samples 1
python3 experiments/comparison/animation.py build/comparison
python3 experiments/comparison/geometry.py build/comparison
python3 experiments/comparison/color.py build/comparison
python3 experiments/comparison/check.py build/comparison
python3 experiments/comparison/run.py build/comparison
task test
```

`check.py` exits **1** when any required behavior fails. Malformed ICC profiles now require assumed-sRGB fallback. `color.py` compares every
pixel against an analytical reference (RGB tolerance 2, alpha 1); it also runs the
Rust-only public API reproducer, without Qt processing. Both scripts return failure
for unmet requirements. Passing does not qualify a production backend. `--filter capsule` reruns only
matching checks and merges observations into `checks.json`. A full run replaces it.
`run.py --case gif` replaces only that case's measurements when binary hashes and
repetition counts match the existing report.
`run.py` collects observations rather than enforcing acceptance; it records failures
and returns success after writing its report. Inspect outcomes and pixels separately.
It uses three warmups and twenty measured repetitions, rotated backend ordering,
and concurrency one. OS disk cache is uncontrolled.

Generated corpus, reports, traces and binaries remain under ignored `build/comparison`.
The report contains hashes, package/compiler/build details, per-operation observations,
startup/first-response latency, sampled summed RSS, cgroup CPU and transferred bytes.
The direct-provider control uses the same worker/IPC without bubblewrap. It is not
an in-process application baseline. Timings include systemd scope startup and sampling;
they cannot establish application display or decoder-only speedups.

`qt-worker` compiles the existing provider source files directly, preserving its Qt,
libwebp and libexif paths without importing installation rules. Its GIF reader follows
Viewer's read/delay/count/rewind behavior using an owned buffer. `glycin-worker` links
the Rust static library and reuses provider EXIF parsing inside the outer sandbox.
No encoded data or Qt image serialization travels back to the parent.

The private protocol is a four-byte big-endian JSON length (1–65536), JSON object,
then exactly `bytes` raw bytes. Request payloads are bounded at 256 MiB; SVG main
documents at 10 MiB. Load captures owned bytes; decode, inspect/metadata (Qt), SVG,
pull-frame, restart and close operations remain private. Raster bounds never upscale;
SVG bounds may upscale. Responses use owned premultiplied RGBA8 sRGB pixels; layout
is checked before QImage construction and again by the receiving harness. The output label is not proof of conversion; independent full-pixel checks and
bounded backend diagnostics are recorded separately. Malformed-profile rejection
diagnostics may be unavailable; assumed-sRGB fallback retains an uncertainty note.

Each process tree is launched in a private systemd scope with `MemoryMax=2G` and
`MemorySwapMax=0`; no manager or memory support means explicit launch failure.
Each IPC request has a 15-second deadline. Terminal cleanup has one five-second
budget: scope TERM, at most one second of grace, scope KILL if needed, launcher reaping
and verified hierarchical cgroup cleanup. The Rust session ABI is serialized;
its cancellation entry is not a thread-safe active-decoder interrupt. No sandbox
failure starts a direct-provider fallback.

The bubblewrap runtime contains an explicit codec-plugin set plus its dynamic
library closure, a private `/tmp`, and private PID/network namespaces. Glycin gets
an explicit generated seven-format loader configuration and only the image-rs/SVG
loader executables; executable/configuration discovery cannot use the original
environment. Its client-side EXIF orientation, ICC parsing/conversion and memory
format transformations run inside the outer sandbox. Glycin still explicitly selects
its own Bwrap loader sandbox. The launcher and runtime inventory are experimental,
not a reviewed production packaging mechanism.

SVG fixture capsules stage captured main and descendant raster bytes privately.
The scoped launcher seals memfds and supplies bubblewrap's `--ro-bind-data`; the
resulting read-only files have no live source-directory backing. Both candidates
validate references inside isolation, reject symlinks and unsafe forms, and render
only `/capsule/main.svg`. The check replaces the original main and resources after
capture. This historical fixture mechanism remains available. The descriptor acquisition path below
adds bounded acquisition of a narrower subset; production integration and packaging remain prerequisites.

`geometry.py` generates JPEGs using native `cjpeg -quality 100` and injected
little/big-endian TIFF tags, plus GIFs using explicit blocks and literal LZW codes.
It checks all native pixels against independent coordinate mappings (RGB tolerance
2, alpha exact), dimensions at native/shrinking/no-upscale bounds, captured policy,
repeated inspection, restart, known GIF frames/delays/end and intrinsic loop facts.
`geometry.json` and `geometry/` retain raw responses, hashes, diagnostics, expected,
actual and difference RGBA files; previous reports are copied by content hash.

Private inspection/decode facts use `source_width/height` for stored geometry,
`oriented_width/height` for policy-dependent display geometry, `orientation` for the
effective EXIF value 1–8 and `orientation_policy` for Apply/Ignore. Load defaults to
Apply; restart retains the captured bytes and policy. An explicit conflicting policy
fails. Pixel orientation remains in the backend; common Qt output processing only
converts color and premultiplies. Glycin's public effective orientation API supplies
the inverse geometry calculation without a second EXIF parse or decoder session.

The additional private `gif-facts.h` parser runs over captured bytes inside the
outer helper sandbox, without decompression, Qt GIF decoding or added dependencies.
It reports `intrinsic_loop` with supplemental provenance, scan status, raw repeat
declaration, normalized total plays and infinite state. A complete scan without a
declaration means one play; zero means infinite; positive values mean repeats after
the initial play. Unavailable facts have null counts/state and an explicit reason.
Traversal requires a trailer and is limited to 256 MiB input, 65,536 blocks/subblocks
and 1 MiB extension payload. Identical declarations are accepted; conflicting ones
are unavailable. The private `gif-scan` operation exposes this fact independently of
loader failure. Qt's native `loop_count` remains separate: in these fixtures it
recognizes NETSCAPE2.0 but ignores ANIMEXTS1.0. Neither intrinsic fact describes
`loop_animation(false)`, frame exhaustion or manual restart.

`animation.py` independently generates GIF89a palettes, rectangles, disposal controls
and literal LZW data, and composites expected pixels without candidate codecs. It
checks exact native frames, delays, stable exhaustion and restarts for disposal 1–3,
transparency, local palettes and mixed loop declarations. It then runs sequential
fresh-worker traversal/restart retention workloads on a deterministic 128-frame GIF.
Each workload requires 64 measured checkpoints; first/last eight medians may grow at
most 32 MiB in each of summed RSS and cgroup anonymous memory. A shared 180-second
request deadline cap covers both workloads per candidate; the normal 15-second
request limit and 2 GiB scope ceiling remain. Missing measurements are unproven.
Timestamped series also record `memory.current` and process counts. Every closure
must leave an empty or removed scope. Synthetic analyzer traces run before workers.

Every invocation creates a unique ignored `build/comparison/animation-*/` directory
with responses, fixtures, exact pixel differences, hashes, retention checkpoints,
series and diagnostics. Pixel failures are recorded while processing rather than
accumulating retention pixels in parent memory. Memory classification is separate
from frame correctness; either failure produces nonzero exit. This is a bounded
regression gate after warmup, not leak-freedom or streaming-memory proof. See the
local design for preserved candidate failures; no backend corrections are applied.

GIF diagnosis is separate from acceptance:

```sh
cp build/comparison/rust/release/animation-repro build/comparison/glycin-animation-repro
python3 experiments/comparison/animation-triage.py build/comparison --self-check
python3 experiments/comparison/animation-triage.py build/comparison
python3 experiments/comparison/animation.py build/comparison --skip-retention
```

`animation-repro` is an automatically discovered Cargo binary in the private crate;
`qt-animation-repro` is built only by this standalone experimental CMake project.
Neither uses provider processing or the bridge. The triage runner validates fixture
blocks and clear/literal streams, checks hand-calculated canvases, reduces the three
original seeds (at most 32 trials each), and runs each final/control/exhaustion pair
three times sequentially. Its unique `animation-triage-*/` directory contains definitions,
GIF bytes, expected/actual/difference RGBA, first differences, request traces, scope
closure, diagnostics, reduction history, identities and a hash manifest. Wrapper
comparison checks outcomes, frame dimensions, delays and pixels; absent dimensions
on end normalize to zero and end delays are excluded. All raw fields remain recorded.
Failures and incomplete probes return nonzero. `--skip-retention` preserves existing
compositing checks while reusing prior retention evidence; default acceptance is unchanged.

## Bounded caller-device acquisition

```sh
cmake --build build/comparison --target capture-tests capture-probe
ctest --test-dir build/comparison --output-on-failure
python3 experiments/comparison/capture.py build/comparison
```

The private `source-capture.h` API accepts a caller-owned open, readable, seekable
`QIODevice&`, an explicit positive byte limit (at most 256 MiB) and atomic cancellation.
It seeks to zero, requests chunks of at most 64 KiB and counts actual bytes without
trusting size or EOF hints. A one-byte probe at the limit detects excess input without
retaining it. Ownership/open state remain with the caller; final position is unspecified.
Zero-byte reads mean EOF for these synchronous devices. Empty input succeeds, while
changes observed during reading become part of the capture; no atomic snapshot is claimed.
Failures return no partial payload: IO/device failures are `IoFailure`, invalid limits
and overflow `ResourceLimit`, observed cooperative cancellation `Cancelled`. Checks
surround seek/read and precede success; they cannot interrupt blocking device operations.

`capture-probe PATH BYTE_LIMIT` opens the file in its caller, invokes capture and emits
raw bytes on stdout only after success, with stderr diagnostics and nonzero failure exit.
`capture.py` passes those bytes through unchanged isolated worker IPC after replacing or
removing the original. It checks inspection equality and independent expected PNG,
orientation-6 JPEG and self-contained SVG pixels for both candidates. Every run creates
a unique ignored `build/comparison/capture-*/` directory containing reports, captures,
expected/actual pixels, hashes and scope cleanup. Failed or incomplete checks exit 1.
The final recorded run passes 16/16 checks; all twelve worker scopes close cleanly.
The [design](../../docs/sdd/glycin-feasibility/DESIGN.md) records evidence and limits.

The historical Python adapter and evidence remain available. The linked-resource milestone
below adds a private filesystem identity policy. Blocking-read interruption, active-decoder
cancellation and production migration remain deferred; neither backend is selected or qualified.

## Bounded isolated-request cancellation

```sh
python3 experiments/comparison/cancellation.py build/comparison --focused
python3 experiments/comparison/cancellation.py build/comparison
```

`Worker.request(..., cancel_event=threading.Event())` accepts caller cancellation.
Requests, close and teardown are serialized; another thread only sets the event.
Checkpoints surround nonblocking transfers, control/layout validation and final result
delivery. Observed cancellation discards the reply and makes the session terminal.
`RequestCancelled` is raised only after successful cleanup; `CleanupError` retains
cancellation and cleanup details when proof fails. Further requests fail locally;
recovery requires an explicitly constructed worker. Events set after a returned result
have no effect on that completed request. The existing 15-second operation limit and
any earlier workload deadline remain.

All terminal paths share one idempotent five-second monotonic cleanup budget, measured
from cancellation observation when applicable. Cleanup resolves the unique scope even
before sampling, sends scope TERM, grants at most one second of grace, then uses scope
KILL if needed and reaps the launcher. Manager commands and waits use the remaining
budget. Success requires a removed cgroup or `cgroup.events` with `populated=0`, which
includes descendant cgroups. Missing identity/proof, manager failures and exhausted
budgets fail explicitly. There is no sampled-PID fallback. A scope disappearing during
signalling is accepted only with independent empty/removed cgroup proof. Closing a
cancelled session releases descriptors and artifacts without IPC or another deadline;
stderr remains available.

The focused runner uses bounded event barriers, transport hooks and stderr peer
acknowledgements for pre-transfer, blocked input, response waiting, partial control and
pixel records, EOF/malformed/timeout races, failed manager/deadline boundaries, repeated
cleanup and terminal reuse. The TERM-resistant descendant check deliberately omits
bubblewrap so PID-namespace teardown cannot mask the required scope KILL. Candidate
checks use a deterministic PNG captured by the C++ probe, cancel at acknowledged
request dispatch and immediately before delivery, and repeat each cold/loaded-session
case three times per backend. Each cancellation has an independent fresh-worker pixel
recovery and verified scope cleanup. Dispatch proves an outstanding request, not codec
entry; cooperative decoder interruption remains unproven. Glycin's exclusive-access
cancellation ABI is never invoked concurrently.

Every run writes a unique ignored `build/comparison/cancellation-*/report.json` with
binary/fixture hashes, phase acknowledgements, observation/return/cleanup timestamps,
exceptions, manager diagnostics, launcher status and cgroup proof. Missing scenarios,
unavailable isolation and failed cleanup return nonzero. Both candidates remain
experimental; preserved GIF failures and deferred production/resource-acquisition
policies are unchanged.

The recorded full run `build/comparison/cancellation-1bh6wat8/report.json` passes
35/35 checks and verifies all 59 original/recovery scopes. The longest successful
observation-to-cleanup interval is 1.019 seconds; the hostile descendant records scope
KILL and launcher status -9. Capture rerun `build/comparison/capture-9ksnx411/report.json`
passes 16/16, capture CTest passes 1/1, protocol fault checks pass 5/5 and provider
`task test` passes 3/3 including the installed-package consumer. Python compilation,
changed-peer formatting and whitespace checks pass. Repository-wide `task format-check`
still reports existing violations in unchanged `gif-facts.h` and `qt-worker.cpp`.


## Bounded linked SVG acquisition

```sh
cmake --build build/comparison --target linked-probe linked-tests qt-worker glycin-worker
python3 experiments/comparison/linked-check.py build/comparison --focused
python3 experiments/comparison/linked-check.py build/comparison
```

`linked.acquire` is a private caller adapter accepting caller-owned open base-directory
and main-file descriptors plus the main name relative to that directory. `linked-probe`
duplicates the descriptors with close-on-exec and retains them through discovery and
publication. It captures the main through `Comparison::capture` with the existing 10 MiB
SVG ceiling. Its initial length/bytes output is for isolated discovery only, not a published
capsule. The caller sends those bytes to `svg-resources` in a fresh Qt worker with no source
mounts or inherited source descriptors. Discovery and completed-capsule validation share
an extractor derived from `capsuleAllowed` and the provider resource policy. The parent has
no XML parser or image inspection/decoding step.

Only plain relative local raster image paths in the base or descendants are acquired.
Valid embedded raster and document-local paint/use fragments retain provider semantics.
External URLs, percent encoding, absolute paths, empty/dot/traversal components, backslashes,
queries, linked fragments, xml:base, entities, external CSS and animated reference attributes
fail. Both candidates inspect resource bytes inside isolation and reject nested SVG,
invalid raster and animation-capable linked raster formats. No application inspection occurs.

The parent independently validates the untrusted manifest, then deduplicates names. The
probe repeats validation: at most 256 reference occurrences/unique resources, 1,024 UTF-8
bytes per name, 65,536-byte control records and 256 MiB aggregate captured input including
main. File/directory staging collisions and reserved `main.svg` references fail. Linux
`openat2` uses `RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV` with close-on-exec
and nonblocking flags; only opened regular files are accepted. Unsupported syscall support
fails with no pathname fallback. No original resource tree is enumerated or bound.

Each acquired descriptor's device/inode, mode, size, nanosecond mtime and ctime must match
before/after capture. Before publication every name is reopened under the pinned base and
compared again; the still-open main descriptor and main name are checked too. Observed
mutation, deletion or replacement fails without retry or partial capsule publication.
Renaming/replacing the base pathname leaves the pinned original base authoritative.
This detects observed changes, not an atomic multi-file snapshot: writes between observations
or changes that restore all observed metadata may escape detection. Caller descriptor ownership
is retained; shared file positions may change. Cancellation is cooperative around capture,
transfers and final publication; blocking reads and codec instructions are not cooperatively
interruptible. The adapter's diagnostic barriers are bounded by its 30-second acquisition
budget. A completed byte map is mounted through sealed memfds, mutually exclusive with the
historical `Worker(capsule=...)` fixture-directory input, and both candidates revalidate it.

Every check invocation creates a unique ignored `build/comparison/linked-*/` directory.
Reports retain input/binary hashes, nanosecond resource identities, deterministic barrier
acknowledgements, outcomes, independently expected/actual pixels, discovery/render traces and
scope cleanup proof. Positive same-directory, descendant and repeated-reference scenarios
replace/remove originals, then run both candidates three times in fresh workers. Missing
prerequisites, scenarios, trace or hierarchical scope-cleanup proof yield nonzero exit.
Focused checks precede candidates; existing capture/cancellation, protocol/capsule and provider
installed-package regressions remain required. Color, geometry, GIF, retention and performance
evidence is reused. Neither backend is selected; existing GIF failures remain preserved.

Recorded host verification: `build/comparison/linked-ptqiedit/report.json` passes 36/36,
with all 81 discovery/render scopes verified empty/removed and all 42 positive renders
matching exact expected RGBA (including embedded-raster/document-local-use preservation).
`linked-9yemymri` passes 3/3 focused checks, including strace-injected openat2 ENOSYS;
standalone acquisition/capture CTest passes 2/2. The sequence and logs are in
`build/comparison/linked-verification-ymtj_elb/`: protocol 5/5, historical capsules 16/16,
and provider `task test` 3/3 including installed-package consumer. Capture evidence
`capture-3wv_kfzy` passes 16/16; cancellation `cancellation-r53b_6q9` passes 35/35.
Both worker binary hashes still match those capture/cancellation runs. New C++ files
and changed worker ranges pass clang-format; changed Python compiles and whitespace checks
pass. Full ecosystem/container acceptance and unchanged codec evidence were not repeated.
