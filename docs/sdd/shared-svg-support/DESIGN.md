# Shared SVG support — Design

Add svg.h/svg.cpp beside image.h. Separate byte loading from XML/resource inspection and rendering so applications
retain immutable source bytes. QXmlStreamReader checks root/DTD/attributes/style text before QSvgRenderer::load.
Classify href/xlink:href and CSS url references; only an exclusively local image reference rejection permits the
consumer fallback. Reject CSS escapes conservatively rather than emulate Qt's entire CSS parser. Embedded images
must be base64 PNG/JPEG/GIF/WebP/BMP with a matching raster signature. SVG data URIs are excluded.

Use explicit QtSvg options (DisableAnimations or NoOption; never AssumeTrustedSource). Use QSizeF/QRectF facts,
retain fractional pixel lengths and viewBox-only dimensions, and round once when calculating output pixels.
Revalidate source on rasterization so mutable/forged inspection facts cannot bypass policy. Enforce output bytes
using division before allocating ARGB32_Premultiplied. Cancellation surrounds synchronous Qt calls.

Change provider ownership guidance, README, CMake/package dependencies, CI dependency installation, unit tests
and installed-package consumer. No persistent renderers, caches, workers or UI are introduced.

Qt treats image-element fragment hrefs as filenames rather than document-local references, so these are rejected.
Data URIs must use the lowercase `data:` scheme and contain a decodable raster, preventing Qt's ordinary failed-data
filename fallback. Fragment references in use/paint resources remain allowed. Embedded decode is subject to Qt's
allocation ceiling and renderer resource checks, not the caller's final output-image budget.
