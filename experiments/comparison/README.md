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

# Prepare the explicitly requested standalone animation diagnostic too.
cp build/comparison/rust/release/animation-repro build/comparison/glycin-animation-repro
# Output must not exist. Rebuilds require a freshly prepared bundle.
python3 experiments/comparison/runtime_bundle.py build/comparison \
  --diagnostic build/comparison/rust/release/color-repro glycin \
  --diagnostic build/comparison/glycin-animation-repro glycin \
  --diagnostic build/comparison/qt-animation-repro qt
python3 experiments/comparison/runtime-tests.py
python3 -O experiments/comparison/runtime-tests.py
# This command prepares its own new bundle, including the native diagnostic.
python3 experiments/comparison/runtime-check.py build/comparison --regressions \
  --evidence-dir build/comparison/runtime-acceptance-new

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

Isolated launch requires a prepared `binary.parent/runtime-bundle`; nested diagnostic
callers explicitly select the comparison build's bundle. `runtime_bundle.py` copies
host-native workers, the explicit Qt image plugins, Glycin loaders, bwrap and
xdg-dbus-proxy, MIME data, and their ldd-discovered library closure. Discovery runs
only during preparation, with a minimal environment and absolute tool paths. Nothing
is installed and no host runtime file is modified. An optional `--output` selects a
new bundle directory; pass it as `Worker(..., runtime_bundle=...)` when launching.
The three core workers are mandatory; diagnostic executables must be requested.

Preparation stages and verifies a version-1 manifest before atomic Linux
`renameat2(RENAME_NOREPLACE)` publication. Existing outputs are rejected. Library
aliases are copied as regular files at normalized sandbox destinations. The manifest
records original entry identities, candidate roles, destinations, sizes, modes,
SHA-256 hashes, generated loader configuration and tool/package provenance.
Preflight checks the exact inventory, regular file types, modes, hashes and original
binary identity before creating a scope. Missing/modified bundles, unknown binaries
and wrong roles fail explicitly, without preparation or a direct-launch fallback.
Runtime files are mounted exclusively from the verified bundle; only private capsule
bytes are added. Glycin explicitly selects its own Bwrap sandbox. The parent launcher
and scope manager use absolute host tools and a minimal environment retaining only
required user-manager connection information. The sandbox environment is explicit.

Bundles and manifests are trusted local build artifacts. Integrity checks detect
missing or modified contents; they do not authenticate upstream packages or defend
against concurrent writers to trusted files. This private runtime is not production
packaging. `isolated=False` remains an explicit diagnostic control only.

`runtime-check.py` prepares a fresh bundle and explicitly registers the discovery
diagnostic. It creates a unique ignored `runtime-evidence-*` directory by default;
`--evidence-dir` selects a new directory and refuses existing evidence. The same
option is available on cancellation, capture, linked acquisition and focused checks.
Their standalone destinations remain available; `check.py` also preserves its legacy
`checks.json` aggregate, which the parent never uses as acceptance proof.

Evidence report **version 2** declares the suite, exact invocation options, required
scenario identifiers, per-scenario artifact and scope requirements, scenario results,
all scope lifecycles, artifact inventory and final status. Suite definitions establish
expected identifiers before execution. The parent independently supplies expected
child suites, options, scenarios and evidence requirements. Both zero process status
and a fresh valid child report are mandatory: cancellation 35, capture 16, linked
acquisition 36, protocol 5 and capsules 16. Console summaries are informational.

Reports start failed/incomplete, checkpoint scenarios and constructor/cleanup errors,
and finalize only after structural and artifact validation. Inventory includes every
regular artifact by relative path, size and SHA-256, including nested child reports;
only the invocation's own root `report.json` is excluded. Symlinks, escaping paths,
missing/altered artifacts, missing/duplicate/unexpected/failed scenarios and missing
scope proof fail acceptance. Required artifacts are validated separately from inventory.
Each created scope retains launch intent, unit, commands, constructed environments,
binary/manifest hashes, observed 2 GiB memory and zero-swap limits, launcher reaping
and empty/removed hierarchical cgroup proof within five seconds. A private launcher
release barrier allows limits to be observed before a short-lived control exits.
Injected cleanup failures retain the failed attempt and separate test recovery proof.

Independent host controls prove actual activation through PATH, preload, audit,
soname library search, a deterministic Qt image plugin, executable-adjacent `qt.conf`,
Glycin configuration discovery through each of `GLYCIN_DATA_DIR`, `XDG_DATA_HOME`
and `XDG_DATA_DIRS`, Qt standard-path configuration discovery through XDG configuration
locations, host-file reads and loopback networking. Every control runs in a bounded
user scope with an explicitly constructed environment. Each channel also has a
separate deliberately broken control requiring rejection. Glycin's diagnostic uses
its public cached configuration API without launching the synthetic loader. Only an
existing private dependency feature is enabled; no dependencies or lockfiles are added.
The QPA path remains an environment-exclusion check, not plugin activation proof.
Host configuration is untouched. The bundled diagnostic must exclude all injected
values and canary discovery results under the combined poisoned environment.

Twelve candidate trials retain independent PNG and acquired linked-SVG pixels (three
fresh processes of each kind per candidate), inputs, hashes, commands and raw traces.
Structured syscall findings distinguish successful executions/path operations, failed
lookups and network results, with source-line references. Relative paths, directory
fds, inherited state, PID-namespace translations and Bwrap root changes are tracked;
pathname mentions in argv are not accesses. Successful Glycin trials require both the
expected loader and a distinct successful nested Bwrap execution. Unresolved/truncated
critical evidence fails, including every `???` syscall record. Named noncritical
calls interrupted by recorded termination are retained separately, never as successes.
Trace collection uses strace's seccomp-BPF filter and a recorded 100 ms exit-group
entry delay so outstanding loader calls can settle before thread-group exit. It
changes scheduling only, preserves syscall arguments/results, and is not performance
evidence. A graceful wait for traced workers stays within the five-second cleanup budget.

The four launch injections require exact outer/nested stages, execution attempts,
ENOENT or replacement exit 1 as appropriate, matching diagnostics and structured
nested load failures. EOF, protocol errors, timeouts and cleanup failures alone never
satisfy injection contracts. Invalid/missing bundle inputs must fail before scope launch.

Historical version-1 runtime reports, including
`build/comparison/runtime-evidence-1sp0fuij/`, do **not** satisfy this contract.
Unchanged codec, retention and performance evidence is reused; historical timings
do not measure the current launcher. Hashes establish local artifact integrity,
not upstream authenticity or protection against concurrent trusted-file writers.


Fresh verification on **2026-11-06**: 53 deterministic helper tests pass normally and
under `python -O`; the complete invocation passes **52/52** parent records and all
child suites (**35/16/36/5/16**). All **224 created scopes** have verified terminal
cleanup; maximum recorded cleanup is **1.016 s**. The independently reopened parent
inventory contains **4,450 artifacts**. Inputs include retained acquired main/resource
bytes, cancellation payloads and independent expected/output pixels.
The qualifying local report is
[`runtime-v2-acceptance-final/report.json`](../../build/comparison/runtime-v2-acceptance-final/report.json);
separate reopening results are in
[`runtime-v2-independent-validation.json`](../../build/comparison/runtime-v2-independent-validation.json).
Provider `task test` passes **3/3**, including its installed-package consumer. Earlier
failed `runtime-v2-*` invocations remain failed diagnostic evidence; they are not
substitutes for this completed report. Native controls are host-built; container tools
were used only to apply the pinned formatter. No codec, retention or performance
campaign was repeated.

To reproduce only these acceptance gates after the host build above, use a new path:

```sh
python3 experiments/comparison/runtime-tests.py
python3 -O experiments/comparison/runtime-tests.py
python3 experiments/comparison/runtime-check.py build/comparison --regressions \
  --evidence-dir build/comparison/runtime-acceptance-new
task test
```

The runner reopens its completed report and all five child reports. To repeat that
validation in a separate process without executing any scenarios:

```sh
PYTHONPATH=experiments/comparison python3 - <<'PYTHON'
import json
from pathlib import Path
import runpy
from runtime_evidence import validate_report, validate_child
from runtime_suites import scenarios, requirements

suite = runpy.run_path('experiments/comparison/runtime-check.py')
build = Path('build/comparison').resolve()
root = build / 'runtime-acceptance-new'
expected = suite['contract'](True)
validate_report(root, json.loads((root / 'report.json').read_text()), expected,
                suite='runtime', requirements=expected,
                options=dict(regressions=True, build=str(build), evidence_dir=str(root)))
for index, (script, identity, options, _) in enumerate(suite['SUITES']):
    child = root / f'regression-{index}-{script}'
    options = dict(options, build=str(build), runtime_bundle=str(root / 'runtime-bundle'),
                   evidence_dir=str(child))
    validate_child(child, suite=identity, options=options,
                   required=scenarios(identity, options), requirements=requirements(identity, options))
print('Parent and five child reports validated')
PYTHON
```

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

## Fixed GIF attribution

```sh
python3 experiments/comparison/gif-attribution-tests.py
python3 -O experiments/comparison/gif-attribution-tests.py
python3 experiments/comparison/animation-triage.py build/comparison --attribution \
  --evidence-dir build/comparison/gif-attribution-new
python3 experiments/comparison/gif_attribution.py build/comparison/gif-attribution-new
```

Attribution declares 79 required version-2 scenarios before execution and uses fixed
reduced fixtures without greedy reduction. Diagnostic completion can exit zero while
retaining failed candidate qualifications. Missing provenance, disagreement, incomplete
artifacts, or incomplete scope cleanup exits nonzero. Default triage reduction and
GIF acceptance retain their failure exits. The evidence destination must be new.
The last command independently reopens a completed report; it rejects failed reports.

This is a local source-prepared diagnostic. Exact distribution recipes, all applied
patches, Qt tag checkouts, the Glycin 2.2.6 archive and Git checkout, the client source
commit archive and image 0.25.10 crate/extraction reside in ignored `build/gif-sources/`.
`gif_provenance.py` defines required names and validates identities against installed
packages, build metadata, recipe checksums and the loader lock. Download commands must
use `curl --max-time 120` or `timeout 120 git ...`; fetch the recipe's revision/tag and
referenced sources, never a newer substitute. Missing files produce a failed report.
The scratch `build/gif-decoder/` contains the direct public image-rs composited-frame
probe source, manifest, lock and native build. It implements the same bounded protocol
as the raw API reproducers, using `GifDecoder::new(Cursor(snapshot)).into_frames()`;
its image version/features and GIF dependency identities are checked against the loader.
The workspace loader lock includes optional dependencies for other formats; the probe
records those separately rather than equating the entire workspace graph with its GIF
path. Sources/builds stay in scratch; evidence retains regular copies of upstream audit
inputs and hashes of the direct probe's source, manifest, lock and executable.

The driver rebuilds native workers/reproducers, explicitly registers both raw APIs and
the direct decoder in a fresh runtime bundle, and records every response and trace.
A complete run requires 69 paired scenarios (138 scopes) plus six decoder scopes.
Frame comparisons preserve outcomes, dimensions, delays and pixel hashes, rejecting
error outcomes; only absent/zero end dimensions and end delays are normalized. Full
raw responses remain available. Qualification is independently recomputed from retained
pixels and responses during reopening. No production decoder behavior is corrected.

The [local report draft](GIF-UPSTREAM-REPORT-DRAFT.md) records the current **blocked**
result: exact Qt recipe source-archive checksum mismatch. The complete runtime campaign
retains all 144 cleanup proofs and candidate failures; a fresh attribution command
stops at the source gate. This is not completed attribution or backend qualification.

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

Final checks pass: native acquisition CTest **2/2**, pinned formatting of new C++
fixtures, changed-C++ format checks, Python compilation and whitespace checks in both
repositories. The native socket fixture requires execution outside the agent sandbox;
its successful outside-sandbox run is the qualifying CTest result.
