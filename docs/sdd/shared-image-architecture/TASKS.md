# Tasks

- [x] Inspect baseline and inventory fixtures (R1–R6).
- [x] Record contract and design under authorized roadmap.
- [x] Implement owned provider or consumer migration (R1–R6).
- [x] Run focused regressions, clean build and required checks.
- [x] Review diff and record evidence and remaining integration actions.

## Verification — 2026-09-22

Clean Release configure/build in `build/acceptance` with BUILD_TESTING=ON passed, without warnings (GCC 16.2.1, Qt 6.11.2, libexif 0.6.26, libwebp 1.6.0).
`ctest --test-dir build/acceptance --output-on-failure`: 2/2 passed; 12 provider cases plus an independently built and executed installed-package consumer.
`clang-format --dry-run --Werror` for provider headers/sources/tests passed; `reuse lint` passed (21/21 files).
Source provenance: Viewer baseline 08d504f7930e6e358f7c24c3d933115452018c44 (metadata mechanics, WebP fallback, generated test fixtures).
Publication, hosted CI and umbrella pinning remain pending authorization. No claim of integrated state.
