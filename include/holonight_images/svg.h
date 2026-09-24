#pragma once

#include <QRectF>
#include <QSizeF>

#include <holonight_images/image.h>

namespace HolonightImages {
enum class SvgReferenceKind { Fragment, EmbeddedRaster, LocalFile, External, Invalid };
enum class SvgResourceReason {
  None,
  LocalImageReference,
  ExternalReference,
  Stylesheet,
  EntityDeclaration,
  UnsupportedCss,
  InvalidEmbeddedImage
};
enum class SvgAnimation { Disabled, Enabled };
struct SvgFacts {
  QSizeF defaultSize;
  QRectF viewBox;
  QSizeF documentSize;
};
struct SvgInspection {
  Outcome outcome = Outcome::Damaged;
  SvgResourceReason resourceReason = SvgResourceReason::None;
  SvgFacts facts;
};
struct SvgSource {
  Outcome outcome = Outcome::Damaged;
  QByteArray bytes;
};
struct SvgRenderOptions {
  QSize bound;  // Required positive pixel bound; enlargement is allowed.
  qint64 outputBytes = 0;
  SvgAnimation animation = SvgAnimation::Disabled;
};
struct SvgRenderResult {
  SvgInspection inspection;
  QImage image;
};
// Same device ownership/position contract as image.h. The actual read is bounded,
// even when size() is stale or underreported. SVGZ is not accepted by inspection.
SvgSource loadSvg(QIODevice& source, qint64 inputBytes, const std::atomic_bool& cancelled);
SvgReferenceKind classifySvgReference(QStringView reference);
// These helpers also support a consumer-owned renderer for local linked images.
QSizeF svgDocumentSize(QSizeF defaultSize, QRectF viewBox);
QSize svgPixelSize(QSizeF documentSize, QSize bound);
// Resource validation always precedes loading a renderer. Only an
// exclusively LocalImageReference rejection is eligible for Viewer's local path.
SvgInspection inspectSvg(const QByteArray& bytes, const std::atomic_bool& cancelled,
                         SvgAnimation animation = SvgAnimation::Disabled);
// Revalidates bytes; caller-supplied inspection facts cannot bypass resource policy.
SvgRenderResult rasterizeSvg(const QByteArray& bytes, const SvgRenderOptions& options,
                             const std::atomic_bool& cancelled);
}  // namespace HolonightImages
