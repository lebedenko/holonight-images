// SPDX-License-Identifier: GPL-3.0-or-later
#include "protocol.h"

#include "../device.h"

#include <QColorSpace>
#include <QJsonArray>
#include <QJsonDocument>
#include <QtEndian>

#include <cmath>
#include <cstring>
#include <span>

namespace HolonightImages::Isolation {
namespace {
void require(bool condition) {
  if (!condition) {
    throw ProtocolError("invalid isolated protocol record");
  }
}
QString string(const QJsonObject& record, const char* key) {
  require(record[key].isString());
  return record[key].toString();
}
QJsonObject object(const QJsonObject& record, const char* key) {
  require(record[key].isObject());
  return record[key].toObject();
}
QJsonObject metadata(const MetadataResult& metadataResult) {
  QJsonObject record{{"outcome", static_cast<int>(metadataResult.outcome)},
                     {"make", metadataResult.facts.make},
                     {"model", metadataResult.facts.model},
                     {"lens", metadataResult.facts.lens}};
  auto put = [&](const char* key, auto value) { record[key] = value ? QJsonValue(double(*value)) : QJsonValue(); };
  put("aperture", metadataResult.facts.aperture);
  put("exposure", metadataResult.facts.exposureSeconds);
  put("focal", metadataResult.facts.focalLengthMm);
  put("iso", metadataResult.facts.iso);
  put("latitude", metadataResult.facts.latitude);
  put("longitude", metadataResult.facts.longitude);
  put("altitude", metadataResult.facts.altitudeMeters);
  return record;
}
Outcome outcome(const QJsonObject& record) {
  return Outcome(integer(record, "outcome", 0, static_cast<int>(Outcome::Cancelled)));
}
MetadataResult readMetadata(const QJsonObject& record) {
  MetadataResult metadataResult;
  metadataResult.outcome = outcome(record);
  metadataResult.facts.make = string(record, "make");
  metadataResult.facts.model = string(record, "model");
  metadataResult.facts.lens = string(record, "lens");
  auto get = [&](const char* key) -> std::optional<double> {
    require(record.contains(key));
    if (record[key].isNull()) {
      return {};
    }
    require(record[key].isDouble() && std::isfinite(record[key].toDouble()));
    return record[key].toDouble();
  };
  metadataResult.facts.aperture = get("aperture");
  metadataResult.facts.exposureSeconds = get("exposure");
  metadataResult.facts.focalLengthMm = get("focal");
  if (!record["iso"].isNull()) {
    metadataResult.facts.iso = static_cast<quint32>(integer(record, "iso", 0, UINT32_MAX));
  } else {
    require(record.contains("iso"));
  }
  metadataResult.facts.latitude = get("latitude");
  metadataResult.facts.longitude = get("longitude");
  metadataResult.facts.altitudeMeters = get("altitude");
  return metadataResult;
}
QJsonObject inspection(const Inspection& inspectionResult) {
  return {{"outcome", static_cast<int>(inspectionResult.outcome)},
          {"format", QString::fromLatin1(inspectionResult.format)},
          {"width", inspectionResult.sourceSize.width()},
          {"height", inspectionResult.sourceSize.height()},
          {"orientedWidth", inspectionResult.orientedSize.width()},
          {"orientedHeight", inspectionResult.orientedSize.height()},
          {"orientation", static_cast<int>(inspectionResult.orientation)},
          {"metadata", metadata(inspectionResult.metadata)}};
}
Inspection readInspection(const QJsonObject& record, const Request& request) {
  Inspection inspectionResult;
  inspectionResult.outcome = outcome(record);
  inspectionResult.format = string(record, "format").toLatin1();
  inspectionResult.sourceSize = {static_cast<int>(integer(record, "width", -1, INT_MAX)),
                                 static_cast<int>(integer(record, "height", -1, INT_MAX))};
  inspectionResult.orientedSize = {static_cast<int>(integer(record, "orientedWidth", -1, INT_MAX)),
                                   static_cast<int>(integer(record, "orientedHeight", -1, INT_MAX))};
  inspectionResult.orientation =
      QImageIOHandler::Transformations(static_cast<int>(integer(record, "orientation", 0, 7)));
  inspectionResult.metadata = readMetadata(object(record, "metadata"));
  if (inspectionResult.outcome == Outcome::Success) {
    const auto& limits = request.options.limits;
    require(inspectionResult.sourceSize.width() > 0 && inspectionResult.sourceSize.height() > 0 &&
            inspectionResult.sourceSize.width() <= limits.sourceExtent &&
            inspectionResult.sourceSize.height() <= limits.sourceExtent &&
            static_cast<qint64>(inspectionResult.sourceSize.width()) * inspectionResult.sourceSize.height() <=
                limits.sourcePixels &&
            static_cast<qint64>(inspectionResult.sourceSize.width()) * inspectionResult.sourceSize.height() <=
                limits.decodedBytes / 4);
    auto oriented = inspectionResult.sourceSize;
    if (request.options.orientation == OrientationPolicy::Apply &&
        inspectionResult.orientation.testFlag(QImageIOHandler::TransformationRotate90)) {
      oriented.transpose();
    }
    require(oriented == inspectionResult.orientedSize);
  }
  return inspectionResult;
}
int colorId(const QColorSpace& color) {
  if (!color.isValid()) {
    return 0;
  }
  for (int namedSpace = QColorSpace::SRgb; namedSpace <= QColorSpace::Bt2100Hlg; ++namedSpace) {
    if (color == QColorSpace(QColorSpace::NamedColorSpace(namedSpace))) {
      return namedSpace;
    }
  }
  return -1;
}
}  // namespace
qint64 integer(const QJsonObject& record, const char* key, qint64 low, qint64 high) {
  require(record[key].isDouble());
  const double number = record[key].toDouble();
  require(std::isfinite(number) && number >= static_cast<double>(low) && number <= static_cast<double>(high) &&
          std::floor(number) == number);
  return static_cast<qint64>(number);
}
int pixelDepth(int format) {
  // Explicit wire allowlist; never construct a QImage with an unchecked enum.
  switch (QImage::Format(format)) {
    case QImage::Format_Mono:
    case QImage::Format_MonoLSB:
      return 1;
    case QImage::Format_Indexed8:
    case QImage::Format_Alpha8:
    case QImage::Format_Grayscale8:
      return 8;
    case QImage::Format_RGB16:
    case QImage::Format_RGB555:
    case QImage::Format_RGB444:
    case QImage::Format_ARGB4444_Premultiplied:
    case QImage::Format_Grayscale16:
      return 16;
    case QImage::Format_ARGB8565_Premultiplied:
    case QImage::Format_RGB666:
    case QImage::Format_ARGB6666_Premultiplied:
    case QImage::Format_ARGB8555_Premultiplied:
    case QImage::Format_RGB888:
    case QImage::Format_BGR888:
      return 24;
    case QImage::Format_RGB32:
    case QImage::Format_ARGB32:
    case QImage::Format_ARGB32_Premultiplied:
    case QImage::Format_RGBX8888:
    case QImage::Format_RGBA8888:
    case QImage::Format_RGBA8888_Premultiplied:
    case QImage::Format_BGR30:
    case QImage::Format_A2BGR30_Premultiplied:
    case QImage::Format_RGB30:
    case QImage::Format_A2RGB30_Premultiplied:
    case QImage::Format_CMYK8888:
      return 32;
    case QImage::Format_RGBX64:
    case QImage::Format_RGBA64:
    case QImage::Format_RGBA64_Premultiplied:
    case QImage::Format_RGBX16FPx4:
    case QImage::Format_RGBA16FPx4:
    case QImage::Format_RGBA16FPx4_Premultiplied:
      return 64;
    case QImage::Format_RGBX32FPx4:
    case QImage::Format_RGBA32FPx4:
    case QImage::Format_RGBA32FPx4_Premultiplied:
      return 128;
    default:
      return 0;
  }
}
QJsonObject requestControl(const Request& request, qint64 bytes) {
  const auto& limits = request.options.limits;
  return {{"version", 1},
          {"operation", static_cast<int>(request.operation)},
          {"bytes", bytes},
          {"input", limits.inputBytes},
          {"pixels", limits.sourcePixels},
          {"extent", limits.sourceExtent},
          {"decoded", limits.decodedBytes},
          {"metadataBytes", limits.metadataBytes},
          {"tiff", limits.tiffMetadataBytes},
          {"records", limits.metadataRecords},
          {"width", request.options.bound.width()},
          {"height", request.options.bound.height()},
          {"orientation", static_cast<int>(request.options.orientation)},
          {"metadata", request.metadata}};
}
Request parseRequest(const QJsonObject& record, qint64& bytes) {
  integer(record, "version", 1, 1);
  Request request;
  request.operation = Operation(integer(record, "operation", 0, 2));
  bytes = integer(record, "bytes", 0, byteCeiling);
  request.options.limits = {.inputBytes = integer(record, "input", 1, byteCeiling),
                            .sourcePixels = integer(record, "pixels", 1, INT_MAX),
                            .sourceExtent = static_cast<int>(integer(record, "extent", 1, INT_MAX)),
                            .decodedBytes = integer(record, "decoded", 1, byteCeiling),
                            .metadataBytes = integer(record, "metadataBytes", 1, byteCeiling),
                            .tiffMetadataBytes = integer(record, "tiff", 1, byteCeiling),
                            .metadataRecords = static_cast<int>(integer(record, "records", 1, INT_MAX))};
  require(bytes <= request.options.limits.inputBytes);
  request.options.bound = {static_cast<int>(integer(record, "width", -1, INT_MAX)),
                           static_cast<int>(integer(record, "height", -1, INT_MAX))};
  request.options.orientation = OrientationPolicy(integer(record, "orientation", 0, 1));
  require(record["metadata"].isBool());
  request.metadata = record["metadata"].toBool();
  return request;
}
QJsonObject replyControl(Reply& reply, Operation operation, QByteArray& pixels) {
  pixels.clear();
  QJsonObject record{{"version", 1}, {"operation", static_cast<int>(operation)}, {"bytes", 0}};
  if (operation == Operation::Inspect) {
    record["inspection"] = inspection(reply.inspection);
    return record;
  }
  if (operation == Operation::Metadata) {
    record["metadata"] = metadata(reply.metadata);
    return record;
  }
  auto& decoded = reply.decoded;
  auto& image = decoded.image;
  const int color = colorId(image.colorSpace());
  if (!image.isNull() && (color < 0 || (pixelDepth(image.format()) == 0))) {
    decoded.outcome = Outcome::Unsupported;
    image = {};
  }
  record["outcome"] = static_cast<int>(decoded.outcome);
  record["inspection"] = inspection(decoded.inspection);
  if (decoded.outcome != Outcome::Success) {
    return record;
  }
  require(!image.isNull() && image.sizeInBytes() <= byteCeiling);
  const qint64 stride = (((static_cast<qint64>(image.width()) * image.depth()) + 31) / 32) * 4;
  require(stride * image.height() <= byteCeiling);
  pixels = QByteArray(stride * image.height(), '\0');
  const auto rowBytes = ((static_cast<qint64>(image.width()) * image.depth()) + 7) / 8;
  for (int row = 0; row < image.height(); ++row) {
    std::memcpy(std::span(pixels).subspan(row * stride).data(), image.constScanLine(row),
                static_cast<size_t>(rowBytes));
  }
  record["bytes"] = pixels.size();
  record["width"] = image.width();
  record["height"] = image.height();
  record["stride"] = stride;
  record["format"] = static_cast<int>(image.format());
  record["color"] = color;
  record["dpr"] = image.devicePixelRatio();
  record["dpmX"] = image.dotsPerMeterX();
  record["dpmY"] = image.dotsPerMeterY();
  record["offsetX"] = image.offset().x();
  record["offsetY"] = image.offset().y();
  QJsonArray palette;
  for (auto value : image.colorTable()) {
    palette.append(static_cast<qint64>(value));
  }
  record["palette"] = palette;
  QJsonObject text;
  for (const auto& key : image.textKeys()) {
    text[key] = image.text(key);
  }
  record["text"] = text;
  return record;
}
// Keep all untrusted response checks before owned image construction in one reviewable path.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
Reply parseReply(const QJsonObject& record, const QByteArray& pixels, const Request& request) {
  integer(record, "version", 1, 1);
  integer(record, "operation", static_cast<int>(request.operation), static_cast<int>(request.operation));
  const qint64 bytes = integer(record, "bytes", 0, qMin(byteCeiling, request.options.limits.decodedBytes));
  require(bytes == pixels.size());
  Reply reply;
  if (request.operation == Operation::Inspect) {
    require(bytes == 0);
    reply.inspection = readInspection(object(record, "inspection"), request);
    return reply;
  }
  if (request.operation == Operation::Metadata) {
    require(bytes == 0);
    reply.metadata = readMetadata(object(record, "metadata"));
    return reply;
  }
  auto& decoded = reply.decoded;
  decoded.outcome = outcome(record);
  decoded.inspection = readInspection(object(record, "inspection"), request);
  if (decoded.outcome != Outcome::Success) {
    require(bytes == 0);
    return reply;
  }
  require(decoded.inspection.outcome == Outcome::Success);
  const auto& limits = request.options.limits;
  const int width = static_cast<int>(integer(record, "width", 1, limits.sourceExtent));
  const int height = static_cast<int>(integer(record, "height", 1, limits.sourceExtent));
  require(static_cast<qint64>(width) * height <= limits.sourcePixels);
  const int format = static_cast<int>(integer(record, "format", 1, 255));
  const int depth = pixelDepth(format);
  require(depth != 0);
  const qint64 stride = (((static_cast<qint64>(width) * depth) + 31) / 32) * 4;
  integer(record, "stride", stride, stride);
  require(stride * height == bytes);
  require(width <= decoded.inspection.orientedSize.width() && height <= decoded.inspection.orientedSize.height());
  if (!request.options.bound.isEmpty()) {
    require(width <= request.options.bound.width() && height <= request.options.bound.height());
  }
  const int color = static_cast<int>(integer(record, "color", 0, QColorSpace::Bt2100Hlg));
  require(record["dpr"].isDouble() && std::isfinite(record["dpr"].toDouble()) && record["dpr"].toDouble() > 0 &&
          record["dpr"].toDouble() <= INT_MAX);
  const int dpmX = static_cast<int>(integer(record, "dpmX", 0, INT_MAX));
  const int dpmY = static_cast<int>(integer(record, "dpmY", 0, INT_MAX));
  const QPoint offset(static_cast<int>(integer(record, "offsetX", INT_MIN, INT_MAX)),
                      static_cast<int>(integer(record, "offsetY", INT_MIN, INT_MAX)));
  require(record["palette"].isArray());
  const auto table = record["palette"].toArray();
  int paletteLimit = 0;
  if (depth == 1) {
    paletteLimit = 2;
  } else if (format == QImage::Format_Indexed8) {
    paletteLimit = 256;
  }
  require(table.size() <= paletteLimit);
  if (depth == 1 || format == QImage::Format_Indexed8) {
    require(!table.isEmpty());
    for (int row = 0; row < height; ++row) {
      for (int column = 0; column < width; ++column) {
        const auto byte = static_cast<quint8>(pixels[(row * stride) + (depth == 1 ? column / 8 : column)]);
        const int index =
            depth == 1 ? ((byte >> (format == QImage::Format_Mono ? 7 - (column % 8) : column % 8)) & 1) : byte;
        require(index < table.size());
      }
    }
  }
  QList<QRgb> palette;
  for (auto value : table) {
    palette.append(static_cast<QRgb>(integer({{"value", value}}, "value", 0, UINT32_MAX)));
  }
  const auto text = object(record, "text");
  for (auto it = text.begin(); it != text.end(); ++it) {
    require(it.value().isString());
  }
  QImage image(width, height, QImage::Format(format));
  require(!image.isNull() && image.bytesPerLine() == stride);
  std::memcpy(image.bits(), pixels.constData(), static_cast<size_t>(bytes));
  image.setColorTable(palette);
  if (color != 0) {
    image.setColorSpace(QColorSpace(QColorSpace::NamedColorSpace(color)));
  }
  image.setDevicePixelRatio(record["dpr"].toDouble());
  image.setDotsPerMeterX(dpmX);
  image.setDotsPerMeterY(dpmY);
  image.setOffset(offset);
  for (auto it = text.begin(); it != text.end(); ++it) {
    image.setText(it.key(), it.value().toString());
  }
  decoded.image = std::move(image);
  return reply;
}
QJsonObject parseControl(const QByteArray& bytes) {
  require(!bytes.isEmpty() && bytes.size() <= controlCeiling);
  QJsonParseError error;
  auto doc = QJsonDocument::fromJson(bytes, &error);
  require(error.error == QJsonParseError::NoError && doc.isObject());
  return doc.object();
}
QByteArray frame(const QJsonObject& record) {
  const auto bytes = QJsonDocument(record).toJson(QJsonDocument::Compact);
  require(bytes.size() <= controlCeiling);
  QByteArray result(4, '\0');
  qToBigEndian(static_cast<quint32>(bytes.size()), result.data());
  return result + bytes;
}
}  // namespace HolonightImages::Isolation
