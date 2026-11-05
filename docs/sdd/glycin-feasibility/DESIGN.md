# Glycin feasibility and compatibility decision

## Orientation, geometry and intrinsic GIF facts, 2026-11-06

**Both candidates remain experimental; no production backend is selected.** This
reassessment supersedes only the stored/display geometry and intrinsic loop-fact
gaps recorded below. It does not qualify complete animation playback.

The private session captures Apply (default) or Ignore with the owned snapshot;
restart retains both and explicitly conflicting requests fail. Qt's transformation
flags normalize to EXIF 1–8. Pinned Glycin 3.1.0 supplies its public effective
orientation; stored dimensions reverse its reported swap only when transformations
were enabled. No additional EXIF interpretation or decoder session supplies geometry.
Orientation stays in each backend; common output conversion does not rotate again.

`experiments/comparison/geometry.py` generates an asymmetric grayscale 24×16 JPEG
with six distinct 8×8 blocks using host `cjpeg`, quality 100. It injects all eight
orientations with both TIFF byte orders and retains an untagged control. Explicit
Python coordinate mappings supply every expected native RGBA pixel, independently
of decoder agreement. RGB tolerance is 2; alpha must equal 255. Every fixture runs
under Apply and Ignore, with repeated inspect/decode/restart, native output, a 12×12
shrinking bound and a 64×64 no-upscale bound. Resampling algorithms are not compared.

| Demonstrated fixture behavior | Direct provider | Isolated Qt | Isolated Glycin |
| --- | --- | --- | --- |
| Untagged + orientations 1–8, both byte orders, both policies | passed 34/34 | passed 34/34 | passed 34/34 |
| Linear Display-P3 RGBA conversion/premultiplication, both policies | passed 2/2 | passed 2/2 | passed 2/2 |
| Ten two-frame GIF fixtures: intrinsic facts, every pixel, 30/70 ms delays, clean exhaustion, restart | passed 10/10 | passed 10/10 | passed 10/10 |
| Nine malformed/ambiguous/budget GIF scans, decoding observed separately | passed 9/9 | passed 9/9 | passed 9/9 |

The ten valid GIFs are written as explicit GIF blocks and literal LZW streams,
independently of Qt encoding: absent declaration; NETSCAPE2.0 and ANIMEXTS1.0 each
with values 0, 1, 2 and 65,535; identical repeated declarations with an unrelated
comment extension and local color tables. Two known black/white full frames and
known delays establish content. No declaration means one total play, zero means
infinite, and positive values mean that many repeats after the initial play.

**An additional parser is required for the Glycin candidate:** private C++
`gif-facts.h` scans captured bytes inside the existing outer sandbox, with no Qt GIF
decoding or new dependency. It validates header/screen/table/block structure and
termination through the trailer without decompressing image data. Limits are
256 MiB input, 65,536 blocks/subblocks and 1 MiB extension payload. Truncated header,
screen/global/local tables, subblock payload, missing trailer, conflicting recognized
declarations and both traversal budgets produce unavailable facts with explicit
reasons and null normalized values. Decoder success is independent: Qt, for example,
still decodes missing-trailer, conflicting and over-budget fixtures. Identical
repeated declarations are accepted. This bounded scanner is supplemental provenance,
not a native Glycin fact or complete GIF validation.

Qt's native loop_count is retained separately. **Failed native coverage:** Qt
reports zero repeats for all four ANIMEXTS1.0 fixtures, including the infinite and
positive-repeat cases; its native fact does not recognize that identifier. The
supplemental fact passes these fixtures in all three controls. Glycin still exposes
no native intrinsic loop declaration. Neither manual restart, end-of-frames nor
`loop_animation(false)` is evidence of an intrinsic declaration.

Native Release Cargo/CMake builds passed. Focused checks passed 165/165; existing
color checks passed 96/96; existing experimental checks passed 31/31; provider
`task test` passed 3/3 including installed-package. A restricted launch failed
explicitly at user systemd bus access, then authorized host runs used unchanged
15-second deadlines, 2 GiB process-tree ceilings, layout validation and sandboxes.
The initial private Qt normalization mistake (5/7 interchanged) is corrected and
its failed report retained; tolerances and production decoding were unchanged.
Ignored `build/comparison/geometry.json` and `geometry/` hold raw responses, fixture
and binary hashes, diagnostics, expected/actual/difference pixels and facts. Reports
are preserved by content hash before replacement. Existing performance evidence is
reused; its hashes describe previous binaries and no benchmarks were rerun.

**Unproven:** disposal, complete playback scheduling, long-run retention, active
decoder cancellation, broader geometry/container combinations, acquisition and
production deployment. Passing these fixtures closes only the demonstrated geometry
and supplemental loop-fact gaps. Production APIs, dependencies, consumers, installer
rules and repository pins remain unchanged.

## Focused color reassessment, 2026-11-06

**No production migration is selected. The malformed-profile blocker is removed
under the revised assumed-sRGB fallback policy.** The supported fixture families
below pass; this is a bounded correctness result, not backend qualification.
The earlier decision and observations are retained below as historical evidence.
Their strict malformed-profile rejection requirement is superseded, and those
old failures are not security findings.

`experiments/comparison/color.py` uses LittleCMS only to construct matrix/TRC ICC
profiles. PNG chunks and scanlines are written directly in Python, independently
of Qt encoding. ICC creation timestamps are fixed for reproducible bytes. The
reference uses declared D65 primaries, the linear Display-P3-to-sRGB matrix,
sRGB transfer function, channel clipping before premultiplication, and rounding.
Neither candidate nor LittleCMS conversion output supplies expected pixels.

Each family has RGB and RGBA, 8-bit and 16-bit cases at native dimensions (10×1
opaque RGB or 40×1 RGBA). Ten neutral/chromatic samples cover transfer conversion
and out-of-sRGB P3 primaries; RGBA repeats each at alpha 0, 0.25, 0.5 and 1.
Every returned pixel is compared, with RGB tolerance 2, alpha tolerance 1 and
exact zero RGB at zero alpha. Tolerances were not widened.

| Fixture family | Direct provider | Qt helper | Rust Glycin | Rust public API only |
| --- | --- | --- | --- | --- |
| Untagged assumed sRGB | passed 4/4 | passed 4/4 | passed 4/4 | passed 4/4 |
| Valid sRGB ICC | passed 4/4 | passed 4/4 | passed 4/4 | passed 4/4 |
| Linear sRGB ICC | passed 4/4 | passed 4/4 | passed 4/4 | passed 4/4 |
| Linear RGB / Display-P3 primaries ICC | passed 4/4 | passed 4/4 | passed 4/4 | passed 4/4 |
| Existing invalid ICC payload fallback | passed 4/4 | passed 4/4 | passed 4/4 | passed 4/4 |
| Truncated valid ICC fallback | passed 4/4 | passed 4/4 | passed 4/4 | passed 4/4 |

Maximum observed channel difference is 1. No incorrect valid-profile conversion
was observed in these fixtures. Unsupported profile families, other containers,
CICP and HDR remain **unproven**. Broader high-bit-depth coverage is also unproven.

Private diagnostics describe the returned backend state, separately from known
fixture classification. Qt exposes the provider output QColorSpace validity,
profile presence and bounded description before harness conversion; this is not
a loader-original profile diagnostic. Valid fixtures have a valid space; untagged
and malformed fixtures do not. Absent versus rejected is **unknown** from this
output. No additional container parser is introduced.

The Rust-only `color-repro` uses pinned public Glycin 3.1.0 without Qt processing,
inside the same outer Worker sandbox/scope plus Glycin Bwrap. It returns native
premultiplied RGBA8, color state, profile presence, bounded raw ICC diagnostics
and pixels. Glycin reports `Srgb` for all cases. Raw ICC reaches the client for
valid and malformed profiles, byte-identical to all 20 tagged fixture profiles;
untagged fixtures have none. Therefore malformed
profiles in this corpus are not removed by the loader. Profile presence and an
sRGB state alone do not establish successful conversion; the independent pixel
comparison supplies the valid-fixture evidence. Malformed fallback retains an
explicit uncertainty note even when rejection diagnostics are unavailable.

The pinned `icc.rs:40–63` discards scoped worker `Result`s and returns `Srgb`.
`dbus.rs:348–382` initializes `Srgb`, logs an ICC conversion error and retains
pixels/state; profile-read failure can also bypass conversion. These are source-level
error-propagation concerns, not a demonstrated valid-profile runtime failure or
vulnerability. Invalid profile data reaches this path, but acceptable fallback
pixels cannot prove an internal worker error was surfaced. No crate patch, loader
fork, upgrade or report submission occurred. A local report draft is alongside
the experiment.

Generated profiles, PNGs, fixture/profile/binary hashes, all expected/actual pixels,
differences, diagnostics and stderr live under ignored `build/comparison/color`.
Prior results are copied to content-hash-named files before replacement; earlier
checks were preserved as `checks-before-color-policy.json`. The first restricted
launch failed explicitly at systemd access; the authorized host run used the
unchanged 15-second request deadline and 2 GiB process-tree ceiling. No sandbox
failure falls back to a direct backend.

Native Cargo and CMake Release targets build against host libraries. Focused color
checks pass 96/96, then existing experimental checks pass 31/31 under the revised
policy. Provider `task test` passes 3/3 CTest entries including installed-package.
The earlier performance evidence below is reused without benchmark reruns; its
binary hashes describe the earlier binaries, not these diagnostic builds.

This removes only the demonstrated malformed-profile blocker and qualifies the
listed color fixtures. All previously unproven orientation, animation, acquisition,
isolation deployment and performance scenarios remain unproven; existing Rust
geometry/loop-fact failures remain. No production APIs, dependencies, installation
rules, repository pins or pinned Glycin crate change.

## Historical Rust and Qt helper comparison (superseded color policy), 2026-11-06


**Recommend no production migration. Neither experimental candidate passes the
required color gate.** Both return successful sRGB-labelled pixels for an independent
PNG with a malformed ICC profile. Untagged sRGB defaults must not silently cover a
declared profile that cannot be interpreted. The seven-format smoke corpus, alpha,
16-bit SDR example, EXIF facts and linked SVG examples work; these observations do
not establish comprehensive compatibility.

The new [standalone comparison](../../../experiments/comparison/README.md) implements
two runnable, non-installed candidates and a common bounded JSON/raw-pixel harness.
Production APIs, consumers, dependency declarations, install rules and umbrella pins
are unchanged. There is no private upstream fork. The original C API experiment below
is retained as historical evidence; its EXIF/resource conclusions do not describe the
Rust API candidate.

### Corrected metadata and resource findings

Glycin **Rust crate 3.1.0** declares `COMPAT_VERSION=2` and successfully communicates
with installed **glycin 2.2.6-1** loaders. These are separate versions. The private
Cargo.lock fixes dependency resolution; native Cargo Release and CMake Release builds
use host libraries. GLib/GIO Rust bindings are pinned to matched 0.22.10 releases.
The public [Rust Loader API](https://docs.rs/glycin/3.1.0/glycin/struct.Loader.html)
and the downloaded crate source were inspected; latest-version API documentation
was not used as evidence for protocol-2 behavior.

`ImageDetails::metadata_exif()` returns 324 raw TIFF bytes for the SONY fixture.
The outer isolated helper adds the APP1 `Exif\0\0` signature expected by the provider's
existing libexif entry point. **All ten facts and units pass**: SONY, ILCE-7M4,
FE 24-70mm F2.8 GM II, f/8, 0.01 seconds, 32 mm, ISO 100, latitude +50.45 degrees,
longitude -30.52 degrees and altitude +179 metres. Empty C text metadata never proved
the absence of Rust EXIF access. No application-side EXIF parser is introduced.

`Loader::new(captured_capsule_file)` plus `use_expose_base_dir(true)` renders both
same-directory and descendant raster references. The path is a captured private main,
never the original document. Both candidates first run the provider's SVG policy
checks and the experimental descendant/symlink validation inside the outer sandbox.
Private captured resource files are sealed and copied into read-only bubblewrap data
mounts. Positive rendering has the same pixel hash in both candidates. Traversal,
symlink, absolute path, file URL, network URL and external XML subset cases fail
explicitly. Replacing the original main and resource files after capture leaves the
captured rendering intact. Arbitrary production resource-tree acquisition remains
an integration requirement; fixture capsules do not solve it.

### Isolation and color audit

The Qt worker compiles the actual provider image/metadata/SVG sources, retaining
libwebp fallback and libexif. GIF pull requests use Viewer's QImageReader behavior
without modifying Viewer. The Rust bridge uses opaque serialized sessions, owned
input/result buffers, panic containment, load inspection, frame requests, cancellation
and cleanup. Its cancellation entry requires exclusive access; concurrent cooperative
decoder cancellation is unproven. Parent scope termination handles active requests.

Both helpers run in bubblewrap with an explicit plugin/library runtime, no original
source directory, private temporary storage and private network/PID namespaces.
Glycin explicitly selects Bwrap again for its loader. Generated configuration lists
only the existing seven raster/SVG formats and the installed image-rs/SVG executables.
The environment is cleared before parsing. A systemd user scope enforces 2 GiB across
the process tree with swap disabled; the harness verifies `memory.max`. Missing
namespace, runtime, loader or scope support is an explicit failure, never fallback.
Each IPC operation has a 15-second deadline, TERM, a one-second grace period, then
scope KILL/reap. Invalid control length, oversized payload, invalid stride, crash and
hang peers fail explicitly; their scopes are empty or removed after teardown.
A traced negative probe cannot open an original fixture or connect to a listening
host loopback socket. This is Linux host evidence, not portable deployment attestation.

In glycin 3.1.0, `api_loader.rs` parses EXIF orientation in the client, and `dbus.rs`
calls client-side `icc.rs` before memory-format conversion. These operations are
therefore enclosed by the outer helper sandbox. The audited ICC path logs conversion
errors while retaining an sRGB state, and worker-thread transformation results are
not propagated reliably. Independently, Qt can discard an invalid PNG profile and
return pixels without a valid QColorSpace. The shared invalid-iCCP PNG probe returns
success from **both** candidates. Fixing the contract needs an isolated mechanism
that distinguishes absent profiles from rejected profiles and propagates conversion
failure; silently relabelling the returned pixels is insufficient. This experiment
does not establish that a fork is necessary or that a helper can solve every profile
case. That mechanism remains the next gate.

### Requirement classification

Statuses apply to the measured fixtures and mechanisms only. An unproven row blocks
qualification just as a failed row does. No deferred acceptance is reported as passed.

| Requirement | Qt helper | Rust Glycin | Evidence or remaining work |
| --- | --- | --- | --- |
| Seven-format smoke, static SVG, alpha and bounded output | passed | passed | Nine cases; returned pixel hashes match direct provider |
| Full seven-format compatibility corpus | unproven | unproven | Smoke is not complete format qualification |
| Ten structured EXIF facts with units | passed | passed | Independent provider SONY fixture, raw Rust EXIF verified |
| Missing/damaged metadata and independent external cache PNG attributes | unproven | unproven | Historical Qt-generated PNG text is not external-cache qualification |
| Owned bounded source snapshots, seek/read faults, stale size | passed | passed | Shared Python device adapter; actual bytes checked, caller remains open |
| Production-style QIODevice adapter, live source growth and cancellation while acquiring | unproven | unproven | No production bridge or QIODevice fault matrix added |
| Inspection with source/oriented geometry and eight Apply/Ignore orientations | unproven | failed | Rust response currently supplies oriented geometry only; full matrix deferred |
| Raw pixel layout, extent/stride/length limits and owned QImage copy | passed | passed | Helper and receiver validation; malformed peer checks |
| Untagged alpha and one 16-bit SDR PNG to RGBA8 | passed | passed | Expected premultiplied [100,50,25,128] |
| Explicit failure for malformed/unsupported color | failed | failed | Invalid ICC PNG returns successful sRGB-labelled pixels |
| Supported wide-gamut profile accuracy, CICP and all high-bit SDR cases | unproven | unproven | One 16-bit sample does not qualify these paths |
| Capsule same-directory/descendant rendering and original replacement | passed | passed | Sealed fixture data mounts; same positive pixel hash |
| Traversal/symlink/absolute/file/network/external XML rejection | passed | passed | Explicit negative fixture outcomes inside isolation |
| Arbitrary resource acquisition and complete URI/nested-resource policy | unproven | unproven | Descendant raster fixtures only; no arbitrary tree integration |
| Two GIF pixels, 30/70 ms delays, clean end and restart | passed | passed | Pull requests, no harness playback scheduler |
| Intrinsic finite loop fact | passed | failed | Qt reports repeat=1; private Rust response has no intrinsic loop fact |
| GIF disposal, infinite loops, long-run retention, active decode cancellation | unproven | unproven | No comprehensive animation/cancellation stress corpus |
| Bubblewrap execution and denied host file/network probes | passed | passed | Outer runtime trace/probe; nested Glycin Bwrap selected |
| Controlled executable/config discovery, no unsandboxed fallback | passed | passed | Cleared environment; runtime allowlist; explicit launch failures |
| 15-second request limit, 2 GiB tree ceiling and fault teardown | passed | passed | Verified cgroup cap; hanging peer cleanup, empty/removed scopes |
| Exhaustive malicious runtime/configuration and decoder-hang cleanup | unproven | unproven | Protocol peer hang is not an actual hostile decoder |
| Native Release fresh startup/first output, identical bounds, 3+20 runs | passed | passed | 621 raw observations, interleaved concurrency one |
| Reused loader sessions, batches, cached PNGs, memory hits and steady GIF timing | unproven | unproven | Deferred after color failures |
| Copy latency breakdown and zero-copy/cancellation lifetime stress | unproven | unproven | Transport byte counts recorded, individual copy costs not timed |
| No production contract/install/pin changes and no private fork | passed | passed | Standalone targets only; provider installed-package tests pass |

### Measured tradeoffs

The run contains three warmups plus twenty measured repetitions of each of nine
cases per backend: **621 observations**, no transport errors. Median/p95 milliseconds
below include fresh worker/scope startup, source IPC, parsing, pixel postprocessing,
return IPC and instrumentation. Each column uses the same input and output bound.
OS disk cache is uncontrolled. The provider control uses the same IPC worker without
bubblewrap; it is **not** an in-process application benchmark. The harness measures
startup and first-output phases separately in raw JSON. SVG zoom requests are also
recorded; Rust explicitly reloads a still image for each further zoom request.

| Case | Direct provider control | Qt helper | Rust Glycin |
| --- | ---: | ---: | ---: |
| Alpha PNG thumbnail | 39.67 / 53.88 | 39.02 / 55.67 | 67.28 / 79.34 |
| 2048×1024 PNG thumbnail | 44.33 / 55.27 | 51.83 / 64.82 | 68.84 / 80.96 |
| Full 2048×1024 JPEG | 52.64 / 70.16 | 64.48 / 78.96 | 96.25 / 124.70 |
| EXIF JPEG | 32.12 / 41.77 | 38.24 / 52.57 | 55.80 / 66.27 |
| Static SVG first raster | 32.61 / 38.92 | 43.00 / 48.81 | 69.54 / 85.13 |
| GIF first frame | 35.84 / 45.49 | 46.94 / 51.61 | 62.58 / 79.74 |

Across this deliberately small mixed corpus, median sampled summed process RSS is
32,260 / 33,790 / 58,022 KiB (control / Qt / Rust), and median cgroup CPU usage is
16,597.5 / 25,462.5 / 87,075 microseconds. These mixed-case summaries do not predict
real workload peaks. RSS samples omit between-sample peaks and instrumentation has
cost; cgroup CPU includes the launcher and all scoped children. Reports record raw
per-case RSS/CPU and transport bytes. Source/output hashes, package versions, compiler,
CMake cache, Rust profile, Cargo.lock hash and measured executable hashes are retained
in ignored `build/comparison/report.json`; checks and traces are alongside it.
No thresholds are inferred from the historical five-sample debug experiment.

### Decision, verification and prerequisites

Both candidates fail the required color behavior, so **neither is recommended**.
The Qt candidate has fewer decoder/sandbox layers and lower fresh-process latency
in this sample, but that does not override a compatibility failure. No production
backend abstraction, migration, commit or publication is included.

Per the plan's negative-result stop condition and proportional-verification guidance,
the remaining exhaustive corpus and session/cache performance scenarios are deferred.
The native experiments build, Python syntax checks pass, the fault/resource/EXIF/GIF
and basic SDR checks pass: 29 of 31 focused checks pass, with the two invalid-ICC
checks remaining reproducible failures. GIF startup includes Qt's explicit reader-open
operation; that case was rerun separately with unchanged measured executable hashes
after correcting the timing interval.
`task test` passes all three provider CTest entries, including the installed-package
consumer. Broader ecosystem/container acceptance is unwarranted without installed
contract changes.

Before a later migration: prove explicit isolated color rejection/conversion; restore
complete source/oriented geometry and intrinsic GIF loop facts for Rust; finish every
unproven compatibility/isolation row; design QIODevice/resource acquisition and stable
identity handling; qualify cancellation during actual decoding and bound retained
frames; package and attest the runtime with fail-closed discovery; then measure reused
sessions, thumbnail/cache workloads, steady GIF frames and copy costs. Only candidates
passing those gates can be compared for production selection. Prefer fewer custom
components and no fork among qualifying candidates; preserve installed consumers and
installer staging/ownership/collision/uninstall checks during any separately authorized
migration.

## Historical C API experiment, 2026-11-05

Date: 2026-11-05. Scope: standalone experiment, no production interfaces frozen.

## Decision

**Block production migration with the currently installed C API.** Ordinary raster
pixels, orientation and PNG text metadata work in the experiment, but structured EXIF
and stream-based linked SVG resources do not meet compatibility requirements. Do not
advance the provider rewrite or introduce a temporary Qt/SVG fallback. All current
consumers still use the previous backend.

This is a negative feasibility result, not completion of all milestone-one acceptance.
The experiment and small baseline are reproducible. Comprehensive performance,
confinement, mutation and deployment qualification remain blocked by the mechanisms
below. Spending on full application acceptance before resolving them is deferred.

## Host and method

Host packages observed: Glycin 2.2.6-1, bubblewrap 0.13.1-1, Qt base 6.12.0-3,
Qt imageformats 6.12.0-1 and Qt SVG 6.12.0-1; GNU C++ 16.2.1. This differs from
the original investigation's Glycin 2.2.5. The authoritative API examined was
`/usr/include/glycin-2/glycin.h` and loader configs under
`/usr/share/glycin-loaders/2+/conf.d`. Executables under `/usr/lib/glycin-loaders/2+/`
are image-rs, svg, heif and jxl. Configured MIME types include AVIF/HEIF/JXL,
but their presence is not qualification. No formats are newly advertised.

The [experiment](../../../experiments/glycin/README.md) uses an owned byte snapshot
and a memory stream; Glycin receives no source pathname in those modes. A bounded
QIODevice adapter, read/seek faults, live growth and concurrent replacement have not
been prototyped. The diagnostic path mode intentionally is not a candidate production
adapter. Caller QFile stays open, and the memory stream was not closed by decoding.

The restricted Codex environment rejected IPC startup with `Operation not permitted`;
there was no successful image or fallback. Host execution was separately authorized.
The probe explicitly selects BWRAP and refuses the sandbox-disable environment override.
An `execve` trace confirmed `/usr/bin/bwrap` with `--unshare-all`, `--seccomp`,
read-only `/usr` and `/usr/lib/glycin-loaders/2+/glycin-image-rs` actually launched
for the PNG stream probe (`build/glycin/sandbox-exec.log`). This demonstrates startup
on this host, not portable sandbox attestation. Deployment still needs failure
tests for missing loaders, namespace denial and malicious/overridden configuration.
The installed library contains `GLYCIN_DISABLE_SANDBOX` and `GLYCIN_DATA_DIR` override
names; reject/sanitize these before library initialization in a production design.
AUTO's documented Flatpak development exception is unsuitable for a fail-closed contract.

## Observed compatibility

Five fresh-process samples per case, sequentially. Raw samples and corpus SHA-256
hashes are in ignored `build/glycin/report.json`; regenerate using the README.

| Requirement | Observation | Decision |
| --- | --- | --- |
| PNG/JPEG/BMP, GIF first frame | Byte and memory-stream decoding succeeds | Feasible subset only |
| RGBA/alpha lifetime | Requested RGBA8 premultiplied; validate extent, stride, length, format, copy into owned QImage | Candidate copy contract; no zero-copy API commitment |
| Alpha PNG | Source (200,100,50,128); round-trip (199,100,50,128) after premultiplication | Expected 8-bit rounding, preserve alpha |
| PNG text | `Thumb::URI` and `Thumb::MTime` survive | Promising for cache isolation; external fixtures still required |
| Orientation | Tag 6 transforms 4×3 to 3×4; Ignore retains 4×3; API dimensions also change with policy | Do not confuse returned dimensions with original source geometry |
| Scaling | 2048×1024 PNG remains full size despite 32×32 request; static SVG scales to 32×16 | Output checks are mandatory; scaling is not an allocation limit |
| Static SVG | Solid rectangle renders | Basic raster request works |
| Linked SVG | Local, parent and escaping symlink cases return transparent pixels in stream and diagnostic path mode | Same-directory compatibility fails; transparent output is not confinement proof |
| Cancellation | Pre-cancelled and timer-cancelled async load tested on private context | Not proof of interrupting a decoder mid-frame, bounded teardown or child cleanup |
| GIF | Two known delays and no-loop end observed separately from first-frame loading | Disposal, intrinsic loop count, restart and bounded buffering remain unqualified |

The linked fixtures use SVG 1.1 `xlink:href` and an embedded raster control. Do not
interpret `ExposeBaseDir=true` as proof that a C byte/stream request supplies a base
directory. No installed C setter conveys a separate directory/resource capability.
Path diagnostic results do not resolve stable main-source ownership either.

## Structured metadata gate

The JPEG fixture is the provider's `sonyPayload()` with real encoded JPEG pixels.
Glycin returns orientation separately, but its key/value metadata for this JPEG is empty.
The installed C header exposes no structured EXIF getters.

| Fact | Fixture value | C API observation |
| --- | --- | --- |
| Make | SONY | Absent |
| Model | ILCE-7M4 | Absent |
| Lens | FE 24-70mm F2.8 GM II | Absent |
| Aperture | f/8 | Absent |
| Exposure | 0.01 seconds | Absent |
| Focal length | 32 mm | Absent |
| ISO | 100 | Absent |
| Latitude | +50.45 degrees | Absent |
| Longitude | −30.52 degrees | Absent |
| Altitude | +179 metres | Absent |

A necessary extension must parse these facts **inside the isolated loader**, bound
records/strings and return optional typed values with documented units and best-effort
status through IPC and C accessors. Parsing returned raw EXIF with application libexif
would leave the original exposure. This experiment does not implement a private fork
or claim such an extraction path exists.

## Resource and color contracts to resolve

Linked SVG needs an audited mechanism accepting main-document bytes plus a separate
directory capability, enforcing descendants-only resolution inside isolation, and
binding resources to one request. Required cases include URI decoding, nested links,
absolute/file/network URLs, DTDs/stylesheets, symlink escapes and mutations of main,
child and intermediate directories. Decide immutable resource snapshots versus
reject/retry before choosing a production interface. Read-only binds do not freeze
host mutations. Do not implement another application-side XML validator as a bridge.

Selected display policy for later implementation: SDR/sRGB, RGBA8 premultiplied,
orientation applied exactly once (or deliberately ignored), owned Qt pixels. Untagged
inputs use the documented backend default only after qualification. ICC-to-sRGB is
explicitly requested; only an sRGB-tagged fixture was tested here. Wide-gamut/invalid
ICC, CICP, high bit depth, gamut clipping and HDR remain unqualified. Do not simply
relabel CICP/ICC pixels as sRGB. Determine where profile parsing/conversion occurs;
the C conversion switch does not establish that it executes in isolation. If host-side
profile parsing is required, moving that operation inside isolation is another gate.

Capabilities must distinguish configured loader MIME types, qualified application
formats and per-request success. Preserve the seven-format contract pending corpus
qualification; no SVG animation, SVGZ, HDR or new format features are authorized here.

## Performance baseline and limits

The initial five-sample run records full-resolution decoder operations, SVG's 32×32
request and GIF first-frame startup, not application first display. OS caches were
uncontrolled and the application/loader were fresh per sample. No speedup target or
regression threshold is inferred from this small synthetic corpus.

Native CMake build type was unset (no optimization flag requested). Kernel was
Linux 7.2.14-arch1-1, x86_64, glibc 2.44. XDG_DATA_HOME/XDG_DATA_DIRS were present;
GLYCIN_DISABLE_SANDBOX/GLYCIN_DATA_DIR were absent. Representative medians from the
185-observation run, in milliseconds:

| Fixture | Qt | Glycin bytes | Glycin stream |
| --- | ---: | ---: | ---: |
| 64×32 alpha PNG | 7.816 | 22.993 | 17.847 |
| 2048×1024 PNG | 10.372 | 34.263 | 40.422 |
| 2048×1024 JPEG | 4.414 | 37.293 | 36.593 |
| Static SVG | 1.175 | 44.323 | 39.455 |
| GIF first frame | 3.836 | 19.284 | 19.467 |

Large PNG stream copy times were 2.683–3.455 ms. Application peak RSS across all
cases was 26,912–63,036 KiB; this range is not a backend comparison or combined peak.
Five timer cancellations returned cancellation errors; the GIF produced 30,000 and
70,000 microsecond delays followed by NO_MORE_FRAMES. The embedded SVG control
rendered alpha pixels while every local/escape resource case remained transparent.

Warm in-memory/disk-thumbnail hits, thumbnail batches, full GIF steady playback,
SVG zoom/DPR quality, total application-plus-loader peak RSS and loader CPU are not
measured. The report records application RSS/CPU and copy time only. These omissions
prevent performance acceptance. Establish representative corpus and quantitative
thresholds after the metadata/resource mechanisms work and before rollout.

## Verification and next gate

The standalone native probe compiles with warnings enabled. The existing native
provider CTest suite and installed-package consumer passed (three CTest entries).
Production sources, exports and dependency declarations are unchanged. No container
or ecosystem acceptance was warranted by this non-installed experiment.

Next work is a version-specific upstream/private loader API investigation for isolated
structured metadata and stream-plus-resource capabilities. Re-run this corpus against
that candidate, prove isolation and resource confinement including replacement races,
then complete color/animation/performance qualification before production contracts.
