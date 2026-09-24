# Verification

## Resumed local acceptance — 2026-09-24

- `cmake --build build/maintenance-acceptance -j 2` and
  `ctest --test-dir build/maintenance-acceptance --output-on-failure`: passed
  both provider CTest entries, including 19 unit tests and installed-package use.
- `cmake --build build/fuzz-maintenance -j 2`: built all three sanitizer
  harnesses. Full log: `build/maintenance-fuzz-build.log`; no compiler warnings.
- `reuse lint`: passed outside the sandbox. Its multiprocessing Unix socket is
  blocked inside the sandbox; both logs are retained under `build/maintenance-reuse*`.

## Retained finding

The earlier 600-second raw-EXIF and metadata campaigns passed. The decode campaign
stopped after 46.8 seconds with exit 77 and a LeakSanitizer report of 7,776 bytes
in 60 allocations, with stacks in the system Qt PDF/PDFium plugin. Earlier
campaigns precede the current harness changes and do not qualify the final harness.
Evidence remains in `build/maintenance-fuzz-{exif,metadata,decode}/campaign.json`.

The 26-byte input is retained at
`build/maintenance-fuzz-decode/artifacts/decode/leak-c6bcf4d7afe044f73e5eab87b4e0441243034661`.
Its base64 is `CiVQREYtR/9JRjj/AQAAEQACAgBEAkwBAC4=` for reproduction if local
build evidence is removed. Replaying it with the current harness on 2026-09-24
again exited 77; see `build/maintenance-decode-replay-unrestricted.log`:

```sh
ASAN_OPTIONS=detect_leaks=1:allocator_may_return_null=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 QT_QPA_PLATFORM=offscreen \
  build/fuzz-maintenance/fuzz/fuzz-decode -runs=1 \
  build/maintenance-fuzz-decode/artifacts/decode/leak-c6bcf4d7afe044f73e5eab87b4e0441243034661
```

LeakSanitizer itself fails under the sandbox's ptrace restriction, so the
unsandboxed replay is authoritative. No leak suppression or production-code
change was introduced. This is a reproducible external-codec finding, not a
successful decode campaign or proof that all decoder allocations are bounded.
The codec defect remains open; no clean fuzz result is claimed for decoding.

## Final harness campaigns

`python3 scripts/fuzz-local.py build/fuzz-maintenance build/maintenance-final-fuzz
--seconds 60` ran outside the sandbox on 2026-09-24. All three seed replays passed.
The EXIF and metadata campaigns completed with exit 0. Decode stopped with exit
77 on another PDF-signature input with leak stacks in Qt PDF/PDFium. Overall
runner exit was 1, correctly preserving the failure. Final source hashes in
`build/maintenance-final-fuzz/campaign.json` were verified against the working tree.

The new artifact is
`build/maintenance-final-fuzz/artifacts/decode/leak-91724a730d1b149d5778515aa73017f5e9a652d8`,
base64 `CiVQREYt/wL/BkdJRjb/////AAAsAAAAACQBAAEAAAIC`.
No clean-decode acceptance claim is made. M-001 delivers the requested opt-in
harnesses and preserves their findings with a failing exit status. Its tooling
requirements are complete. The external-codec leak is an open follow-up; repairing
or restricting production codecs is explicitly outside the accepted package.
