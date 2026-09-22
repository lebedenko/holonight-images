#include "device.h"

#include <QImageReader>
#include <QtEndian>

#include <holonight_images/image.h>
#include <limits>
#include <webp/decode.h>

namespace HolonightImages {
namespace {
bool acceptableSize(QSize size, const Limits& limits) {
  const qint64 pixels = qint64{size.width()} * size.height();
  return size.width() > 0 && size.height() > 0 && size.width() <= limits.sourceExtent &&
         size.height() <= limits.sourceExtent && pixels <= limits.sourcePixels && pixels <= limits.decodedBytes / 4;
}
Outcome readerError(QImageReader& reader) {
  switch (reader.error()) {
    case QImageReader::FileNotFoundError:
    case QImageReader::DeviceError:
      return Outcome::IoFailure;
    case QImageReader::UnsupportedFormatError:
      return Outcome::Unsupported;
    default:
      return Outcome::Damaged;
  }
}
Outcome prepare(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled) {
  if (cancelled.load()) return Outcome::Cancelled;
  if (!source.isOpen() || !source.isReadable() || source.isSequential() || !source.seek(0)) return Outcome::IoFailure;
  if (!valid(limits) || source.size() > limits.inputBytes) return Outcome::ResourceLimit;
  return Outcome::Success;
}
// Only the simple single-bitstream RIFF form is eligible. Extended containers,
// ancillary chunks and animation retain the installed Qt decoder's interpretation.
QImage simpleWebPFallback(QIODevice& file, const std::atomic_bool& cancelled, bool& limited, const Limits& limits) {
  if (cancelled.load() || !file.seek(0)) {
    return {};
  }
  const auto header = file.peek(20);
  if (header.size() != 20 || header.first(4) != "RIFF" || header.sliced(8, 4) != "WEBP" ||
      (header.sliced(12, 4) != "VP8 " && header.sliced(12, 4) != "VP8L")) {
    return {};
  }
  const auto bytes = file.read(qMin(file.size(), limits.inputBytes));
  if (cancelled.load() || bytes.size() < 20 || bytes.size() > limits.inputBytes || bytes.first(4) != "RIFF" ||
      bytes.sliced(8, 4) != "WEBP" || (bytes.sliced(12, 4) != "VP8 " && bytes.sliced(12, 4) != "VP8L")) {
    return {};
  }
  const auto* data = static_cast<const uint8_t*>(static_cast<const void*>(bytes.constData()));
  const quint64 riff_size = qFromLittleEndian<quint32>(bytes.sliced(4, 4).constData());
  const quint64 chunk_size = qFromLittleEndian<quint32>(bytes.sliced(16, 4).constData());
  if (riff_size + 8 != static_cast<quint64>(bytes.size()) ||
      20 + chunk_size + (chunk_size & 1) != static_cast<quint64>(bytes.size())) {
    return {};
  }
  int width = 0;
  int height = 0;
  if (WebPGetInfo(data, bytes.size(), &width, &height) == 0) {
    return {};
  }
  if (!acceptableSize({width, height}, limits)) {
    limited = true;
    return {};
  }
  if (cancelled.load()) {
    return {};
  }
  QImage image(width, height, QImage::Format_RGBA8888);
  if (image.isNull() ||
      WebPDecodeRGBAInto(data, bytes.size(), image.bits(), image.sizeInBytes(),
                         static_cast<int>(image.bytesPerLine())) == nullptr ||
      cancelled.load()) {
    return {};
  }
  return image;
}

// Header-only companion for the same narrowly eligible RIFF bitstream fallback.
void inspectSimpleWebP(QIODevice& device, Inspection& info, const Limits& limits) {
  if (!device.seek(0)) return;
  const auto bytes = device.peek(32);
  if (bytes.size() < 20 || bytes.first(4) != "RIFF" || bytes.sliced(8, 4) != "WEBP" ||
      (bytes.sliced(12, 4) != "VP8 " && bytes.sliced(12, 4) != "VP8L"))
    return;
  const quint64 riff = qFromLittleEndian<quint32>(bytes.constData() + 4);
  const quint64 chunk = qFromLittleEndian<quint32>(bytes.constData() + 16);
  if (riff + 8 != quint64(device.size()) || 20 + chunk + (chunk & 1) != quint64(device.size())) return;
  int width = 0, height = 0;
  if (!WebPGetInfo(static_cast<const uint8_t*>(static_cast<const void*>(bytes.constData())), bytes.size(), &width,
                   &height))
    return;
  info.format = "webp";
  info.sourceSize = {width, height};
  info.orientedSize = info.sourceSize;
  info.outcome = acceptableSize(info.sourceSize, limits) ? Outcome::Success : Outcome::ResourceLimit;
}
Inspection header(QImageReader& reader, const Limits& limits, OrientationPolicy policy) {
  Inspection info;
  const bool readable = reader.canRead();
  info.format = canonicalFormat(reader.format());
  if (!readable) {
    info.outcome = readerError(reader);
    return info;
  }
  info.sourceSize = reader.size();
  info.orientation = reader.transformation();
  info.orientedSize = info.sourceSize;
  if (policy == OrientationPolicy::Apply && info.orientation.testFlag(QImageIOHandler::TransformationRotate90))
    info.orientedSize.transpose();
  if (info.sourceSize.isEmpty())
    info.outcome = Outcome::Damaged;
  else if (!acceptableSize(info.sourceSize, limits))
    info.outcome = Outcome::ResourceLimit;
  return info;
}
}  // namespace
QByteArray canonicalFormat(QByteArray format) {
  format = format.toLower();
  if (format == "jpg" || format == "jpe") return "jpeg";
  if (format == "tif") return "tiff";
  return format;
}
QStringList supportedSuffixes() {
  QStringList suffixes;
  for (const auto& format : QImageReader::supportedImageFormats()) {
    suffixes.append(QString::fromLatin1(format).toLower());
    const auto canonical = canonicalFormat(format);
    suffixes.append(QString::fromLatin1(canonical));
    if (canonical == "jpeg") suffixes.append("jpg");
    if (canonical == "tiff") suffixes.append("tif");
  }
  suffixes.removeDuplicates();
  suffixes.sort();
  return suffixes;
}
Inspection inspect(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled, OrientationPolicy policy,
                   bool metadata) {
  Inspection info;
  info.outcome = prepare(source, limits, cancelled);
  if (info.outcome != Outcome::Success) return info;
  Device device(source);
  {
    QImageReader reader(&device);
    reader.setAutoTransform(policy == OrientationPolicy::Apply);
    info = header(reader, limits, policy);
  }
  if (!cancelled.load() && (info.outcome == Outcome::Unsupported || info.outcome == Outcome::Damaged))
    inspectSimpleWebP(device, info, limits);
  if (device.failed) info.outcome = Outcome::IoFailure;
  if (cancelled.load()) info.outcome = Outcome::Cancelled;
  if (metadata && info.outcome == Outcome::Success) info.metadata = readMetadata(source, limits, cancelled);
  if (cancelled.load()) info.outcome = Outcome::Cancelled;
  return info;
}
DecodeResult decode(QIODevice& source, const DecodeOptions& options, const std::atomic_bool& cancelled) {
  DecodeResult result;
  result.outcome = prepare(source, options.limits, cancelled);
  if (result.outcome != Outcome::Success) return result;
  Device device(source);
  {
    QImageReader reader(&device);
    reader.setAutoTransform(options.orientation == OrientationPolicy::Apply);
    result.inspection = header(reader, options.limits, options.orientation);
    result.outcome = result.inspection.outcome;
    if (cancelled.load()) result.outcome = Outcome::Cancelled;
    if (result.outcome == Outcome::Success) {
      if (!options.bound.isEmpty()) {
        auto target = result.inspection.orientedSize
                          .scaled(options.bound.boundedTo(result.inspection.orientedSize), Qt::KeepAspectRatio)
                          .expandedTo(QSize(1, 1));
        if (options.orientation == OrientationPolicy::Apply &&
            result.inspection.orientation.testFlag(QImageIOHandler::TransformationRotate90))
          target.transpose();
        reader.setScaledSize(target);
      }
      result.image = reader.read();
      if (result.image.isNull()) result.outcome = readerError(reader);
    }
  }  // Reader releases exclusive device access before fallback seeks.
  if (!device.failed && !cancelled.load() &&
      (result.outcome == Outcome::Unsupported || result.outcome == Outcome::Damaged)) {
    bool limited = false;
    result.image = simpleWebPFallback(device, cancelled, limited, options.limits);
    if (limited) result.outcome = Outcome::ResourceLimit;
    if (!result.image.isNull()) {
      result.outcome = Outcome::Success;
      result.inspection.format = "webp";
      result.inspection.sourceSize = result.image.size();
      result.inspection.orientedSize = result.image.size();
      result.inspection.outcome = Outcome::Success;
    }
  }
  if (device.failed) result.outcome = Outcome::IoFailure;
  if (cancelled.load()) result.outcome = Outcome::Cancelled;
  if (result.outcome == Outcome::Success) {
    if (result.image.sizeInBytes() > options.limits.decodedBytes ||
        !acceptableSize(result.image.size(), options.limits))
      result.outcome = Outcome::ResourceLimit;
    else if (!options.bound.isEmpty() &&
             (result.image.width() > options.bound.width() || result.image.height() > options.bound.height()))
      result.image = result.image.scaled(options.bound, Qt::KeepAspectRatio, Qt::SmoothTransformation);
  }
  if (cancelled.load()) result.outcome = Outcome::Cancelled;
  if (result.outcome != Outcome::Success) result.image = {};
  return result;
}
}  // namespace HolonightImages
