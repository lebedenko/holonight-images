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
Installed distribution patches have not been audited; no patched rebuild was tested.
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

The matching installed loader/image-rs dependency source was not available locally;
remote source retrieval did not succeed. Attribution between Glycin client, loader
and image-rs remains incomplete. These are observed public-API failures, not a claim
that a specific upstream layer or source line has been demonstrated faulty.
