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
Each IPC request has a 15-second deadline. Abort sends TERM, allows one second,
then kills the scope and reaps the launcher. The Rust session ABI is serialized;
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
capture. This proves a fixture mechanism, not safe acquisition of arbitrary resource
trees. Production acquisition, identity/race policy and packaging remain prerequisites.

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
