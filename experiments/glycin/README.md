# Glycin feasibility experiment

This standalone, non-installed experiment implements the first migration decision gate.
It does not change the provider, package dependencies or consumers. Run against host
libraries; do not deploy container-built binaries. See the local
[compatibility decision](../../docs/sdd/glycin-feasibility/DESIGN.md).

From `holonight-images`:

```sh
cmake -S experiments/glycin -B build/glycin -G Ninja
cmake --build build/glycin
python3 experiments/glycin/run.py build/glycin --samples 5
```

Dependencies are C++23, Qt Core/Gui, pkg-config, Glycin >= 2.2, Python 3,
installed Glycin loaders/configuration, bubblewrap and working user namespaces.
No GTK dependency is needed. The production CMake build does not include this directory.
Build products, generated corpus, hashes and raw JSON observations stay in ignored
`build/glycin`. The runner returns successfully when observations were collected;
decoder errors are recorded, **not treated as passing compatibility tests**.

Each sample has a fresh application and loader, sequential concurrency one. Disk cache
is uncontrolled. Timings start after reading the encoded input, include loader discovery,
startup, first frame and (for Glycin) validation/copy, but exclude application startup and
file acquisition. Qt uses `QImageReader`, not the provider's WebP/metadata policy paths.
Requested Glycin frame size is 32 by 32; Qt decodes full size. These are a small decoder
baseline, not equivalent end-to-end display benchmarks. The report records every sample,
median/max, hashes, library versions, kernel/host, process CPU and application peak RSS.
RSS is Linux `getrusage(RUSAGE_SELF)` in KiB; it does **not** include loader memory.

The fixture generator reuses the provider's independent EXIF writer. It creates tagged
PNG, JPEG with all EXIF facts, orientation 6, BMP, a larger PNG, static/embedded SVG,
same-directory/parent/symlink SVG references, and a two-frame 30/70 ms GIF. Sources are
small generated fixtures; this does not qualify complete format support.

Probe modes:

| Mode | Purpose |
| --- | --- |
| `qt FILE` | Fresh-process Qt comparison |
| `bytes FILE` | Owned copied `GBytes` source |
| `stream FILE` | Memory stream backed by owned bytes, no pathname conveyed to Glycin |
| `path FILE` | Diagnostic `GFile` comparison only; violates production no-reopen contract |
| `ignore FILE` | Stream input with transformations disabled |
| `cancel FILE` | Pre-cancelled async load on a private GLib context |
| `cancel-running FILE` | Cancel async load after a 1 ms context timer |
| `frames FILE` | Read up to four GIF frames with looping disabled |

Every Glycin mode explicitly selects BWRAP, requests RGBA8 premultiplied and enables
ICC-to-sRGB conversion. The probe refuses `GLYCIN_DISABLE_SANDBOX` even if empty.
Use a trusted host environment: `GLYCIN_DATA_DIR`, XDG data directories, PATH and
installed loader configuration can affect executable selection. This prototype is not
a hardened deployment launcher. It retains no unsandboxed fallback. A private GLib
context is only exercised by cancellation modes.

Read `pixel_rgba`, not just `ok`, for linked SVGs: a successful transparent image means
the reference was not rendered. The embedded raster is the positive control. Inspect
`metadata`, orientation/dimensions, `frame_delays_us`, `end_of_animation`, cancellation
errors and `stream_closed` as separate compatibility observations.

For startup evidence on a host permitting ptrace:

```sh
strace -f -e trace=execve -s 1000 -o build/glycin/sandbox-exec.log \
  build/glycin/glycin-probe stream build/glycin/corpus/alpha.png
```

No changes to system packages, installer ownership, staging or uninstall are needed.
