# Shared SVG support — holonight-images

Approved scope: user-supplied implementation plan, 2026-09-24. Work package SVG-001.
Baseline: `35efad8325f31991deb24149d2e2d8ec388ae8c1`.

## Requirements

- When loading SVG, the provider shall bound both reported and actual bytes from a caller-owned seekable device.
- When inspecting SVG, the provider shall return structured facts and policy reasons without translated text.
- When choosing document geometry, the provider shall prefer valid default size, fall back to finite positive viewBox,
  preserve fractional geometry, and reject unusable dimensions.
- Before loading a renderer, the provider shall reject external resources/stylesheets and entity declarations,
  while allowing fragment references and embedded raster images.
- When rasterizing, the provider shall preserve aspect ratio and transparency, permit enlargement, and enforce
  caller output-byte limits before image allocation without raster logical-coordinate limits.
- The provider shall expose reference classification without opening/resolving paths and distinguish cancellation,
  I/O failure, damaged XML, resource limits and unsupported resource policy.
- The installed package shall resolve Qt SVG explicitly, and basic SVG rendering shall work without the image-reader plugin.
- Raster inspection/decoding contracts shall remain unchanged.

See [design](DESIGN.md) and [tasks](TASKS.md).
