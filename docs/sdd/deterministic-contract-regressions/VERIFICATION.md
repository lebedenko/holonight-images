# Verification — 2026-09-22

Baseline: `efe3e780327fa793fb76c82b18fddde15298120b`, initially clean on `main`.
Changed only `tests/image_test.cpp`, `tests/exif_fixture.h` and this local SDD.

Focused passes used `build/acceptance/tests/images-test` after incremental builds:
initial/later device failures, cancellation at every observed read, exact raster limits,
then the complete metadata/budget/malformed-container cases. The additional PNG/WebP
and multi-block TIFF I/O/cancellation regression also passed individually.

Clean acceptance, from this repository:

```sh
cmake -S . -B build/hardening-acceptance -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build build/hardening-acceptance --parallel 2
ctest --test-dir build/hardening-acceptance --output-on-failure
clang-format --dry-run --Werror include/holonight_images/image.h src/device.h src/image.cpp src/metadata.cpp tests/image_test.cpp tests/exif_fixture.h tests/package-consumer/main.cpp
reuse lint
```

Clean Release build passed without warnings. Full CTest passed 2/2: all 19 provider
cases and the independently configured, built and executed installed-package consumer.
Toolchain: GCC 16.2.1, Qt 6.11.2, libexif 0.6.26, libwebp 1.6.0, GoogleTest 1.18.0.
Formatting passed. REUSE passed after an unsandboxed retry because its multiprocessing
socket was blocked by the sandbox. Full build/CTest logs and installed-consumer output
were reviewed; the existing deliberately truncated PNG test emits an expected codec
read-error diagnostic. No new assertions depend on unspecified codec error classification.

Evidence: `/tmp/shared-hardening-images-{build,focused,container-tests,clean,ctest,license}.log`
and `build/hardening-acceptance/Testing/Temporary/LastTest.log`.
Final `git diff --check`, local SDD link validation and `reuse --no-multiprocessing lint`
passed (25/25 files).

No implementation correction was needed, so consumer rebuilds against a changed provider
artifact are not applicable. Tests remain deterministic; no fuzzing, new dependencies or
public API changes. Publication and umbrella pins are outside this local handoff.
