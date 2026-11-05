# Local draft: Glycin ICC worker results and conversion error state

Not submitted. This is a source-level concern, not a confirmed valid-profile
runtime defect or vulnerability. Malformed-profile fallback is acceptable for
this experiment's display policy.

Environment: Rust glycin crate 3.1.0, loader protocol 2, installed Arch glycin
2.2.6-1 loaders, native Release x86_64 Linux. The private Cargo.lock fixes the
complete Rust dependency graph. Qt host packages used for comparison are
qt6-base 6.12.0-3, qt6-imageformats and qt6-svg 6.12.0-1.

From holonight-images, build with the commands in README.md (including locked
Cargo Release), then run:

```sh
python3 experiments/comparison/color.py build/comparison
```

`rust/src/bin/color-repro.rs` is the minimal public API reproducer. It reads the
bounded private load/decode protocol, uses Loader::new_vec, selects Bwrap,
requests premultiplied RGBA8, calls next_frame and reports raw pixels, ColorState
and FrameDetails::color_icc_profile. It has no Qt postprocessing. The Python
runner supplies the same outer bubblewrap and systemd scope as the comparison;
do not run outside that boundary for this investigation. Generated PNGs and
profiles, exact hashes, raw ICC bytes (hex, limited to 8192 bytes), pixels,
differences and stderr are under build/comparison/color. The analytical reference
is independent of Glycin and LittleCMS conversion output.

Expected: valid matrix/TRC fixture conversion agrees with the analytical SDR
sRGB reference; malformed profiles may fall back. If a conversion fails, the API
should expose reliable failure/state information rather than imply conversion.

Actual: all 24 fixtures pass for the Rust-only reproducer, and all 72 candidate /
control comparisons pass. Valid sRGB, linear sRGB and linear Display-P3 ICCs
convert accurately (maximum channel error 1, required tolerance 2; alpha tolerance
1). Malformed payload and truncated profile produce assumed-sRGB pixels. Raw ICC
is byte-identical to all 20 tagged fixture profiles, including malformed profiles;
absent for untagged PNGs. All returned
states are Srgb. Thus the malformed ICC is not removed by these loaders. This
does not demonstrate an incorrect valid-profile conversion. Rejection diagnostics
are unavailable at the public response used here.

Source evidence, from the locally downloaded unmodified glycin-3.1.0 crate:

- src/icc.rs:40–63: scoped workers return Result<(), lcms2::Error>, but their
  handles/results are discarded. transform returns Ok(ColorState::Srgb) after
  the scope. A worker's profile/transform construction error appears unable to
  propagate through this return value. Thread panic handling is a distinct path.
- src/dbus.rs:348–382: color_state starts at Srgb; ICC application Err logs a
  warning and retains that state and buffer. An ICC BinaryData read error also
  bypasses the Some(Ok(profile)) branch.

Question for upstream review: should worker results be collected and should ICC
failure/fallback have an explicit public diagnostic or distinct color state?
The valid-profile conversion-error path has not been triggered by this corpus.
No crate patch, fork or dependency upgrade was used, and no vulnerability claim
is made. Profile presence and Srgb state alone must not be used as proof of
successful conversion.
