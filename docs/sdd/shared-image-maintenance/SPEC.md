# Shared image maintenance

Approved scope: supplied implementation plan. Work package M-001.
Baseline: `3633865d2f39e4f163f0159a0f252f88245379f0` (clean HEAD and umbrella pin verified 2026-09-23).

## Requirements

- When opted in, tooling shall provide separate off-by-default Clang ASan/UBSan/libFuzzer targets for raw EXIF, container metadata and bounded inspection/decoding.
- Tooling shall preserve production APIs, behavior, codecs and cache policy.
- Verification shall retain raw evidence and failures outside tracked source.
- Publication and umbrella pins shall wait for explicit authorization.

See [design](DESIGN.md), [tasks](TASKS.md) and [verification](VERIFICATION.md).
