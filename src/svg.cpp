#include <QBuffer>
#include <QImageReader>
#include <QPainter>
#include <QRegularExpression>
#include <QSvgRenderer>
#include <QUrl>
#include <QXmlStreamReader>

#include <algorithm>
#include <cmath>
#include <holonight_images/svg.h>

namespace HolonightImages {
namespace {
bool usable(QSizeF size) {
  return std::isfinite(size.width()) && std::isfinite(size.height()) && size.width() > 0 && size.height() > 0;
}
void reject(SvgInspection& result, SvgResourceReason reason) {
  // A later unsafe reference must never be hidden by an earlier local image.
  if (result.resourceReason == SvgResourceReason::None ||
      result.resourceReason == SvgResourceReason::LocalImageReference)
    result.resourceReason = reason;
  result.outcome = Outcome::Unsupported;
}
void reference(SvgInspection& result, QStringView value, bool image) {
  switch (classifySvgReference(value)) {
    case SvgReferenceKind::Fragment:
      // Qt treats an image href as a filename, even when it starts with '#'.
      // Only use/paint references have document-local fragment semantics.
      if (image) reject(result, SvgResourceReason::ExternalReference);
      return;
    case SvgReferenceKind::EmbeddedRaster:
      if (!image) reject(result, SvgResourceReason::ExternalReference);
      return;
    case SvgReferenceKind::LocalFile:
      reject(result, image ? SvgResourceReason::LocalImageReference : SvgResourceReason::ExternalReference);
      return;
    case SvgReferenceKind::External:
      reject(result, SvgResourceReason::ExternalReference);
      return;
    case SvgReferenceKind::Invalid:
      reject(result, SvgResourceReason::InvalidEmbeddedImage);
      return;
  }
}
void css(SvgInspection& result, QString text) {
  // Conservative CSS subset: escapes can disguise resource keywords. Reject
  // them explicitly rather than attempting to duplicate Qt's CSS parser.
  if (text.contains(u'\\')) {
    reject(result, SvgResourceReason::UnsupportedCss);
    return;
  }
  static const QRegularExpression comments(QStringLiteral("/\\*.*?\\*/"),
                                           QRegularExpression::DotMatchesEverythingOption);
  text.remove(comments);
  if (text.contains(QStringLiteral("/*"))) {
    reject(result, SvgResourceReason::UnsupportedCss);
    return;
  }
  static const QRegularExpression imports(QStringLiteral("@\\s*import\\b"), QRegularExpression::CaseInsensitiveOption);
  if (text.contains(imports)) {
    reject(result, SvgResourceReason::Stylesheet);
    return;
  }
  static const QRegularExpression urls(QStringLiteral("\\burl\\s*\\(([^)]*)\\)"),
                                       QRegularExpression::CaseInsensitiveOption);
  auto matches = urls.globalMatch(text);
  while (matches.hasNext()) {
    auto value = matches.next().captured(1).trimmed();
    if (value.size() >= 2 &&
        ((value.front() == u'\'' && value.back() == u'\'') || (value.front() == u'"' && value.back() == u'"')))
      value = value.mid(1, value.size() - 2);
    reference(result, value, false);
  }
  text.remove(urls);
  static const QRegularExpression incompleteUrl(QStringLiteral("\\burl\\s*\\("),
                                                QRegularExpression::CaseInsensitiveOption);
  if (text.contains(incompleteUrl)) reject(result, SvgResourceReason::UnsupportedCss);
}
// Preserve fractional pixel lengths before Qt's integer defaultSize conversion.
std::optional<qreal> pixelLength(QStringView value) {
  auto text = value.trimmed().toString();
  if (text.endsWith(QLatin1String("px"))) text.chop(2);
  bool ok = false;
  const auto number = text.toDouble(&ok);
  if (ok && std::isfinite(number)) return number;
  return std::nullopt;
}
SvgInspection validate(const QByteArray& bytes, const std::atomic_bool& cancelled, QSvgRenderer& renderer) {
  SvgInspection result;
  if (cancelled.load()) {
    result.outcome = Outcome::Cancelled;
    return result;
  }
  QXmlStreamReader xml(bytes);
  bool root = false;
  QString width, height;
  bool declaredViewBox = false;
  while (!xml.atEnd()) {
    xml.readNext();
    if (cancelled.load()) {
      result.outcome = Outcome::Cancelled;
      return result;
    }
    if (xml.isDTD()) {
      // No external subsets or entity declarations; ordinary SVG doctypes are OK.
      if (!xml.entityDeclarations().isEmpty() || !xml.dtdSystemId().isEmpty() || !xml.dtdPublicId().isEmpty() ||
          xml.text().contains(QLatin1String("<!ENTITY")))
        reject(result, SvgResourceReason::EntityDeclaration);
    }
    if (xml.isProcessingInstruction() && xml.processingInstructionTarget() == QLatin1String("xml-stylesheet"))
      reject(result, SvgResourceReason::Stylesheet);
    if (!xml.isStartElement()) continue;
    if (!root) {
      if (xml.name() != QLatin1String("svg") ||
          (!xml.namespaceUri().isEmpty() && xml.namespaceUri() != QLatin1String("http://www.w3.org/2000/svg")))
        return result;
      root = true;
      width = xml.attributes().value(QLatin1String("width")).toString();
      height = xml.attributes().value(QLatin1String("height")).toString();
      declaredViewBox = xml.attributes().hasAttribute(QLatin1String("viewBox"));
    }
    const auto animatedAttribute = xml.attributes().value(QLatin1String("attributeName"));
    if (animatedAttribute == QLatin1String("href") || animatedAttribute == QLatin1String("xlink:href") ||
        animatedAttribute == QLatin1String("src") || animatedAttribute == QLatin1String("xml:base"))
      reject(result, SvgResourceReason::ExternalReference);
    for (const auto& attr : xml.attributes()) {
      if (attr.name() == QLatin1String("href") || attr.name() == QLatin1String("src"))
        reference(result, attr.value(), xml.name() == QLatin1String("image"));
      else if (attr.qualifiedName() == QLatin1String("xml:base"))
        reject(result, SvgResourceReason::ExternalReference);
      else if (attr.name() == QLatin1String("style") || attr.name() == QLatin1String("fill") ||
               attr.name() == QLatin1String("stroke") || attr.name() == QLatin1String("filter") ||
               attr.name() == QLatin1String("clip-path") || attr.name() == QLatin1String("mask") ||
               attr.name() == QLatin1String("cursor") || attr.name().startsWith(QLatin1String("marker")) ||
               attr.name() == QLatin1String("from") || attr.name() == QLatin1String("to") ||
               attr.name() == QLatin1String("values"))
        css(result, attr.value().toString());
    }
    if (xml.name() == QLatin1String("style")) css(result, xml.readElementText());
  }
  if (xml.hasError() || !root) {
    if (result.resourceReason != SvgResourceReason::EntityDeclaration) result.outcome = Outcome::Damaged;
    return result;
  }
  if (result.resourceReason != SvgResourceReason::None) return result;
  if (!renderer.load(bytes)) return result;
  if (cancelled.load()) {
    result.outcome = Outcome::Cancelled;
    return result;
  }
  auto& facts = result.facts;
  facts.defaultSize = renderer.defaultSize();
  facts.viewBox = renderer.viewBoxF();
  // For viewBox-only documents Qt rounds its default size to integer pixels.
  if (declaredViewBox && width.isEmpty() && height.isEmpty()) facts.defaultSize = facts.viewBox.size();
  if (auto value = pixelLength(width)) facts.defaultSize.setWidth(*value);
  if (auto value = pixelLength(height)) facts.defaultSize.setHeight(*value);
  facts.documentSize = svgDocumentSize(facts.defaultSize, facts.viewBox);
  if (usable(facts.documentSize)) result.outcome = Outcome::Success;
  return result;
}
QtSvg::Options rendererOptions(SvgAnimation animation) {
  return animation == SvgAnimation::Disabled ? QtSvg::DisableAnimations : QtSvg::NoOption;
}
}  // namespace

SvgSource loadSvg(QIODevice& source, qint64 inputBytes, const std::atomic_bool& cancelled) {
  if (cancelled.load()) return {Outcome::Cancelled, {}};
  if (inputBytes <= 0) return {Outcome::ResourceLimit, {}};
  if (!source.isOpen() || !source.isReadable() || source.isSequential() || !source.seek(0))
    return {Outcome::IoFailure, {}};
  if (source.size() > inputBytes) return {Outcome::ResourceLimit, {}};
  QByteArray bytes;
  char buffer[16384];
  while (true) {
    if (cancelled.load()) return {Outcome::Cancelled, {}};
    // Read one extra byte at the limit without overflowing the caller's budget.
    const auto request = std::min<qint64>(inputBytes - bytes.size(), sizeof(buffer) - 1) + 1;
    const auto count = source.read(buffer, request);
    if (count < 0) return {Outcome::IoFailure, {}};
    if (cancelled.load()) return {Outcome::Cancelled, {}};
    if (count == 0) break;
    if (count > inputBytes - bytes.size()) return {Outcome::ResourceLimit, {}};
    bytes.append(buffer, count);
  }
  return {Outcome::Success, std::move(bytes)};
}

SvgReferenceKind classifySvgReference(QStringView reference) {
  const auto text = reference.trimmed().toString();
  if (text.startsWith(u'#')) return SvgReferenceKind::Fragment;
  if (text.startsWith(QLatin1String("data:"), Qt::CaseInsensitive)) {
    // Qt's image loader recognizes the data scheme case-sensitively.
    if (!text.startsWith(QLatin1String("data:"))) return SvgReferenceKind::Invalid;
    static const QRegularExpression header(QStringLiteral("^data:image/(png|jpeg|gif|webp|bmp);base64,"),
                                           QRegularExpression::CaseInsensitiveOption);
    const auto match = header.match(text);
    if (!match.hasMatch()) return SvgReferenceKind::Invalid;
    const auto decoded = QByteArray::fromBase64Encoding(text.mid(match.capturedLength()).toLatin1(),
                                                        QByteArray::AbortOnBase64DecodingErrors);
    if (!decoded) return SvgReferenceKind::Invalid;
    QBuffer buffer;
    buffer.setData(decoded.decoded);
    buffer.open(QIODevice::ReadOnly);
    const auto format = QImageReader::imageFormat(&buffer);
    if (format != match.captured(1).toLatin1().toLower()) return SvgReferenceKind::Invalid;
    // Qt falls back to a filename when an embedded image cannot decode. Reject
    // damaged data here, before the SVG loader can take that fallback.
    buffer.seek(0);
    QImageReader reader(&buffer, format);
    if (reader.read().isNull()) return SvgReferenceKind::Invalid;
    return SvgReferenceKind::EmbeddedRaster;
  }
  const QUrl url(text, QUrl::StrictMode);
  if (text.isEmpty() || !url.isValid()) return SvgReferenceKind::Invalid;
  if ((url.isRelative() && url.authority().isEmpty()) || (url.isLocalFile() && url.host().isEmpty()))
    return SvgReferenceKind::LocalFile;
  return SvgReferenceKind::External;
}

QSizeF svgDocumentSize(QSizeF defaultSize, QRectF viewBox) {
  if (usable(defaultSize)) return defaultSize;
  if (std::isfinite(viewBox.x()) && std::isfinite(viewBox.y()) && usable(viewBox.size())) return viewBox.size();
  return {};
}
QSize svgPixelSize(QSizeF documentSize, QSize bound) {
  if (!usable(documentSize) || bound.width() <= 0 || bound.height() <= 0) return {};
  const auto scale = std::min(bound.width() / documentSize.width(), bound.height() / documentSize.height());
  const auto width = documentSize.width() * scale;
  const auto height = documentSize.height() * scale;
  if (!std::isfinite(width) || !std::isfinite(height)) return {};
  return {int(std::clamp<qint64>(qRound64(width), 1, bound.width())),
          int(std::clamp<qint64>(qRound64(height), 1, bound.height()))};
}
SvgInspection inspectSvg(const QByteArray& bytes, const std::atomic_bool& cancelled, SvgAnimation animation) {
  QSvgRenderer renderer;
  renderer.setOptions(rendererOptions(animation));
  return validate(bytes, cancelled, renderer);
}
SvgRenderResult rasterizeSvg(const QByteArray& bytes, const SvgRenderOptions& options,
                             const std::atomic_bool& cancelled) {
  QSvgRenderer renderer;
  renderer.setOptions(rendererOptions(options.animation));
  SvgRenderResult result{validate(bytes, cancelled, renderer), {}};
  if (result.inspection.outcome != Outcome::Success) return result;
  const auto size = svgPixelSize(result.inspection.facts.documentSize, options.bound);
  if (size.isEmpty() || options.outputBytes <= 0 || qint64(size.width()) * size.height() > options.outputBytes / 4) {
    result.inspection.outcome = Outcome::ResourceLimit;
    return result;
  }
  QImage image(size, QImage::Format_ARGB32_Premultiplied);
  if (image.isNull()) {
    result.inspection.outcome = Outcome::ResourceLimit;
    return result;
  }
  image.fill(Qt::transparent);
  {
    QPainter painter(&image);
    renderer.render(&painter, QRectF(QPointF{}, size));
  }
  if (cancelled.load())
    result.inspection.outcome = Outcome::Cancelled;
  else
    result.image = std::move(image);
  return result;
}
}  // namespace HolonightImages
