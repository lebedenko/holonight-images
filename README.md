# HoloNight Images

Synchronous Qt raster inspection, bounded decoding and structured EXIF facts for HoloNight applications.
Extracted from HoloNight Viewer and Files under GPL-3.0-or-later.

Requires CMake 3.25+, C++23, Qt 6.11 Core/Gui, libexif and libwebp. Tests additionally use GoogleTest and Python.
No KDE dependency. Runtime formats come from installed Qt image handlers; AVIF is not guaranteed.

```sh
cmake -S . -B build/release -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/release
ctest --test-dir build/release --output-on-failure
cmake --install build/release --prefix /your/prefix
```

Consumers use `find_package(HolonightImages CONFIG REQUIRED)` and link `HolonightImages::Images`.
The installed-package CTest builds and executes a separate consumer using only the staged prefix.

```cpp
#include <holonight_images/image.h>
const HolonightImages::Limits policy{
    256 * 1024 * 1024, 32000000, 32768, 128 * 1024 * 1024,
    1024 * 1024, 64 * 1024 * 1024, 4096};
const std::atomic_bool cancelled{false};
auto result = HolonightImages::decode(openDevice, {.limits = policy, .bound = {512, 512}}, cancelled);
```

The caller owns an already-open, readable, seekable device and grants exclusive access during each call.
Calls begin at offset zero and leave position unspecified. They never close or reopen the source pathname.
Applications own workers, scheduling, caches, UI and translated errors. Cancellation is checked between operations;
a blocking codec call cannot be interrupted. Set Qt's process-wide allocation ceiling at application startup.
Per-call limits reject input/source dimensions before decoding and validate actual output bytes afterwards;
they cannot account for every internal allocation of third-party codecs.

`inspect` reports canonical format, stored dimensions, intrinsic transformation and policy-oriented dimensions,
and optionally reads EXIF. `decode` reports the same header facts and returns the first raster frame; use
`readMetadata` or `inspect` for EXIF. Output bounds apply after intrinsic orientation and never upscale.
Orientation defaults to Apply exactly once; Ignore exists for consumers that explicitly require stored pixels.
Raster outcomes distinguish Success, Unsupported, Damaged, ResourceLimit, IoFailure and Cancelled. Qt codec
failures without a specific I/O diagnosis are Damaged; an unknown damaged signature may be Unsupported.

Metadata is best effort: absent or malformed tags remain absent, oversized blocks are skipped with ResourceLimit,
and metadata failure does not invalidate an otherwise decodable raster. Structured facts contain values without
application labels, units or translations. JPEG, PNG, WebP and classic TIFF extraction is bounded; BigTIFF EXIF
is not supported. The private fallback accepts only simple single-bitstream WebP RIFF files; extended and animated
containers retain Qt's interpretation. Plugins advertising the same capability have no guaranteed priority
([Qt plugin selection](https://doc.qt.io/qt-6/qimageioplugin.html)).

See [design](docs/sdd/shared-image-architecture/DESIGN.md) and [verification](docs/sdd/shared-image-architecture/TASKS.md).

## Local sanitizer fuzzing

Opt in using a separate Clang build. The normal library and installed package stay
uninstrumented; fuzz targets are never installed.

```sh
cmake -S . -B build/fuzz -G Ninja -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF -DHOLONIGHT_IMAGES_FUZZING=ON
cmake --build build/fuzz --parallel 2
python3 scripts/fuzz-local.py build/fuzz build/fuzz-evidence --seconds 600
```

The runner requires an empty evidence directory, replays generated seeds, then
runs separate raw-EXIF, container-metadata and bounded-decode campaigns. Use
`--harness exif|metadata|decode` to select one. It retains commands, tool versions,
source/binary/seed/corpus hashes, logs and crash artifacts in `campaign.json` and
adjacent files, and exits nonzero on a finding or timeout. Inputs are capped at
1 MiB, RSS at 2 GiB, each input at 10 seconds, each campaign at 600 seconds and
Qt image allocations at 16 MiB. Read/seek faults, cancellation and small resource
budgets are exercised alongside ordinary inputs.

System Qt codecs and libexif/libwebp are not fully sanitizer-instrumented. A
finding is evidence to investigate, not a reason to suppress sanitizer checks.
LeakSanitizer needs an environment without ptrace restrictions. See the
[maintenance verification](docs/sdd/shared-image-maintenance/VERIFICATION.md)
for the retained Qt PDF plugin leak finding and coverage limitations.
