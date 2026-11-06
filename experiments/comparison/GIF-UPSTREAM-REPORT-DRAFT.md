# Local GIF report drafts — not submitted

Reproduce with the README's locked native Release build and `animation-triage.py`.
Evidence directories are identified in the feasibility design. Both API reproducers
run inside the existing 15-second/2-GiB isolation harness. Fixtures are generated
without a candidate encoder, then independently parsed; expected canvases also have
hand-calculated self-checks. Every final case is confirmed in three fresh workers.
No patches or exhaustion latch are applied.

## Qt: local palette used for disposal-2 background

Environment: qt6-base 6.12.0-3, qt6-imageformats 6.12.0-1.
The standalone `qt-animation-repro.cpp` uses only QBuffer/QImageReader plus RGBA
packing. The 256×128 prefix first differs at frame 11, coordinate (130,70): expected
red 19, actual 239. Greedy frame removal retains three frames (original 0,10,11).
This is the smallest found by frame deletion, not a globally minimal GIF.

The controlled 3×2 case is easier to report: full opaque first frame, a one-pixel
local-palette patch at (0,0) with disposal 2 and no transparency, then a patch at
(2,1). On the third canvas, (0,0) should be global background (19,37,61,255);
observed local color 0 is (239,181,23,255). Changing just the patch to the global
palette makes Qt pass. The provider wrapper returns identical frame pixels/delays.

The matching [Qt 6.12.0 GIF source](https://github.com/qt/qtbase/blob/v6.12.0/src/plugins/imageformats/gif/qgifhandler.cpp)
restores via `color(bgcol)` and selects the active local table in `color()`.
This supports a decoder attribution for the controlled opaque-background case.
The five distribution patches have now been audited and do not modify the GIF source.
However, the recipe source-archive checksum does not match the archive generated
from the referenced tag; exact package-source identity remains unresolved. No patched
rebuild was tested. This remains a provisional source explanation.
The [GIF89a specification](https://giflib.sourceforge.net/gifstandard/GIF89a.html)
defines the logical background index in the global table.

## Glycin: disposal-2 pixels and frames after end

Environment: Rust glycin 3.1.0 (locked graph), protocol 2, installed glycin loaders
2.2.6-1. `rust/src/bin/animation-repro.rs` directly selects Bwrap, premultiplied RGBA
and `specific_frame(FrameRequest...loop_animation(false))`, without Qt or C++ ABI.

Opaque disposal 2 returns transparent black instead of the global opaque background.
The original 256×128 prefix differs at frame 2, coordinate (13,7), and the existing
12×8 disposal-2 seed differs at (1,2). Both retain three frames after greedy removal.
The 3×2 global-palette control fails at (0,0); local-palette control fails similarly.
The C++ wrapper agrees exactly on pixels, geometry and delays.

Two distinct full 2×2 frames, with absent/finite 2/infinite 0 declarations, produce
success, success, end, success, end, success with four extra requests. Restart after
exhaustion and midway reproduces the original sequence. Raw API and wrapper agree.
This demonstrates the stable-exhaustion acceptance failure independently of the
bridge. The locked client's `api_loader.rs` documents the loop option as controlling
return of the first frame after the last; it sends false on every request here.
That text does not explicitly promise persistent end responses after an error.
Consequently an upstream persistent-exhaustion contract violation remains unproven.

The matching installed loader source is now available. The Glycin 2.2.6 Git archive
matches the distribution recipe's BLAKE2 checksum, and the recipe SHA256 matches
package `.BUILDINFO`. Its loader lock selects `image` **0.25.10** and `gif` **0.14.2**;
this is separate from the comparison client's locked graph. The image crate archive
matches the loader lock's checksum.

The loader selects `GifDecoder::new` in `glycin-image-rs/src/lib.rs:297`, forwards
`into_frames()` at line 551, and copies `frame.into_buffer().into_raw()` in
`animated.rs:116–130`. The image GIF iterator explicitly ignores the logical
background for web compatibility (`image/src/codecs/gif.rs:252`) and clears disposal-2
regions to transparent. A scratch host-native reproducer uses that exact image version,
its loader-declared image features, and public composited `into_frames()` API.
All six fresh global/local disposal-2 probes agree with the loader's pixels and delays.
This locates the opaque-background policy in the decoder's compositing API rather than
the C++ bridge. It does not establish that image-rs considers its web-compatibility
policy a bug.

Exhaustion is separate: `animated.rs` recreates the iterator and sets `looped = true`;
`lib.rs:217–221` rejects only looped frame zero without storing an exhausted state.
The exact 3.1.0 client source commit is
`215113448d88270d45ae9a095eb14a983a765650`; its API implementation matches the published
crate. Its tests request one end response, as do the installed loader's tests.
Neither the documented option nor those tests establish repeated stable exhaustion.
The application's stable-exhaustion requirement remains unmet; an upstream API
contract violation remains unproven.


## Private attribution evidence, 2026-11-06

This milestone is **blocked, not completed attribution or backend qualification**.
The version-2 suite declares 79 scenarios: four gates, 69 raw/wrapper pairs, and six
direct-decoder probes. The retained runtime campaign is
`build/comparison/gif-attribution-f_nkyxfe/report.json`: 77 comparison/oracle/build
scenarios validate, all 144 worker scopes terminate within the existing cleanup budget
(maximum recorded cleanup 0.316 s), and 33 scenarios retain failed candidate findings.
All 69 raw/wrapper comparisons agree. Its 2,961 regular artifacts include the source
references, responses, expected/actual/difference bytes, structured/raw traces, bundle
identity and scope proofs. Independent structural validation is retained in
`build/comparison/gif-attribution-independent-validation.json`.

Two source gates fail. Canonical archives generated using makepkg's Git checksum
method produce these SHA256 values:

| Source | Recipe checksum | Observed checksum |
| --- | --- | --- |
| qtbase v6.12.0 | `d97ef157dc50bdf0425337e9adede8135ab508a4ab2f1abae7e9cfc42c5f86db` | `f24f106cee5f49a1e0778ec84301467640f6fdbbbcdf61e77623c119ab966208` |
| qtimageformats v6.12.0 | `30226a5944388a918e925127d8f90486d36027567a6cb058ae52b40cab86c64b` | `ab1bc592becd53b7d236936836e70482adf7fa3d2382b67786284ed3544e88de` |

Recipe files match package build metadata; installed GIF plugin and loader bytes match
the cached packages. The GIF plugin belongs to qt6-base, not qt6-imageformats. Tags,
patches and source references are retained, but the archive discrepancy is unexplained.
No newer source was substituted. Retrieval commands use 120-second bounds; local
caches, matching packaging revisions, their upstream tags and archive endpoints were
checked. Snapshot endpoints returned HTTP 400; exact Git tags were fetched instead.
The initial sandbox DNS failure was retried with authorized network access.

A fresh fail-closed invocation is retained in
`build/comparison/gif-attribution-final-blocked/report.json`; source failure leaves the
native-build and 75 runtime scenarios explicitly not run. The earlier completed
runtime evidence is reused because source/report validation did not change its inputs.
An initial report validator name-shadowing error was corrected and reopening passed
before the stronger checksum audit invalidated attribution. Earlier interrupted and
sandbox-rejected runs are diagnostic history, not qualifying evidence.

Unchanged `animation.py --skip-retention` independently exits **1**: **16 passed,
8 failed**, in `build/comparison/animation-20261106-230716-f26328b8`. The first attempt
found a stale default runtime manifest; that bundle was preserved as
`runtime-bundle-before-gif-attribution` and a fresh bundle prepared before this result.
Existing runtime, codec, retention and performance evidence is reused. No latch,
compositor correction, production dependency, lockfile or backend selection changes.
Reports remain local and have not been submitted.
