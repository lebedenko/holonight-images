# Shared SVG support — Provider verification

Date: 2026-09-24. Baseline: `35efad8325f31991deb24149d2e2d8ec388ae8c1`.
Toolchain: GNU C++ 16.2.1, Qt Core/Svg 6.11.2, libexif 0.6.26, libwebp 1.6.0, GTest 1.18.0.

Commands run from the umbrella root unless otherwise noted:

```sh
cmake -S holonight-images -B holonight-images/build/svg-dev -G Ninja -DCMAKE_BUILD_TYPE=Debug -DBUILD_TESTING=ON
cmake --build holonight-images/build/svg-dev --parallel 2
holonight-images/build/svg-dev/tests/images-test --gtest_filter='Svg.*'
cmake -S holonight-images -B holonight-images/build/svg-acceptance-20260924 -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON
cmake --build holonight-images/build/svg-acceptance-20260924 --parallel 2
ctest --test-dir holonight-images/build/svg-acceptance-20260924 --output-on-failure
```

- Debug focused SVG tests passed, initially 16 then 17 after the CSS identifier regression was added.
- Clean Release configure/build completed without compiler warnings. Complete build and CTest logs were inspected.
- Initial combined-suite acceptance exposed a test isolation failure: Qt retained a plugin already cached by raster
  tests despite changing library paths. The plugin-free check now runs in a separate executable/process.
- Final policy review found Qt image href fragments have filename semantics, and failed data images may fall back
  to filenames. Reject image fragments and non-lowercase data schemes, validate embedded raster decoding first,
  and retain use/paint fragments. Added rejection regressions, rebuilt affected targets and reran acceptance.
- Final focused SVG run: 17/17 passed. Final CTest: 3/3 passed (`images`, `installed-package`,
  `svg-without-image-plugin`). `images` contains 36 tests: 19 existing raster/metadata and 17 new SVG tests.
- The installed consumer uses only the staged package and exercises both raster and SVG symbols. The separate
  plugin-free process confirms SVG is absent from QImageReader formats before rendering and checking alpha/colors.
- Expected libpng Read Error diagnostics come from deliberate damaged-input tests; no actionable build warnings.
- clang-format --dry-run --Werror passed for svg.h, svg.cpp, both SVG test sources and package-consumer/main.cpp.
- git diff --check passed. REUSE lint passed (single-process invocation in the provider); local SDD links validated.

Local raw logs (ignored build artifacts): `build/svg-acceptance-20260924.log`,
`build/svg-acceptance-correction-20260924.log`, `build/svg-policy-correction-20260924.log`.
The last log contains final passing acceptance after corrections to the original clean build.

## Coverage and limitations

Covers distinct default/viewBox dimensions, viewBox-only and absent dimensions, fractional pixel geometry,
finite/positive fallback, enlargement, transparency, logical dimensions exceeding raster budgets, exact output
budgets, invalid bounds, large integer bounds, malformed XML/SVGZ, retained bytes, device ownership/offset,
reported/actual byte limits, read/seek/sequential/closed failures, cancellation before/during reads,
fragment/CSS/href/xlink policy, local versus external classification, entity/stylesheet rejection,
embedded PNG rasterization and static animation disabling.

Physical-unit dimensions retain Qt's default-size interpretation. Embedded rasters are decoded for validation;
Qt's process-wide allocation ceiling and renderer checks still govern intermediates. Output-byte limits govern
final QImage allocation; cancellation cannot interrupt a Qt call. No new persistent renderers or UI exist here.

Provider publication/CI and umbrella pin changes are pending authorization. Viewer/Files implementation,
consumer task check, isolated runtime acceptance and manual ecosystem checks remain pending. The initiative is
not Integrated. This provider verification does not assert consumer compatibility at a future revision.
