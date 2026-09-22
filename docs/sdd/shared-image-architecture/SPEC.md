# holonight-images: shared image architecture

Approved scope: user implementation roadmap, 2026-09-22.

- R1: Processing shall use a caller-owned open seekable device without reopening a path.
- R2: Raster operations shall enforce explicit input/source/output limits and return typed outcomes.
- R3: Orientation shall default to Apply; Files shall explicitly select Ignore.
- R4: The provider shall own discovery, EXIF parsing and the narrow WebP fallback. Consumers shall retain formatting, worker scheduling, caching and presentation.
- R5: Existing raster inputs, alpha, navigation/cache behavior, descriptor identity and stale-result rejection shall remain covered by regressions.
- R6: The library shall install a standalone CMake package with Qt Core/Gui, libexif and libwebp dependencies only.
