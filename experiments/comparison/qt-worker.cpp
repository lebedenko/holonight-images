// SPDX-License-Identifier: GPL-3.0-or-later
#include <QBuffer>
#include <QColorSpace>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPainter>
#include <QSvgRenderer>
#include <QXmlStreamReader>
#include <QtEndian>

#include "gif-facts.h"

#include <atomic>
#include <cstdio>
#include <holonight_images/image.h>
#include <holonight_images/svg.h>
#include <memory>

#ifdef WITH_GLYCIN
extern "C" {
void* comparison_new();
int comparison_load(void*, const unsigned char*, size_t, bool, bool);
int comparison_frame(void*, unsigned, unsigned);
const unsigned char* comparison_result(const void*, size_t*, bool);
void comparison_free(void*);
}
QJsonObject bridgeControl(void* session) {
  size_t length = 0;
  const auto* data = comparison_result(session, &length, false);
  if (length > 65536) return {{"outcome", "control-limit"}};
  return QJsonDocument::fromJson(QByteArray(reinterpret_cast<const char*>(data), qsizetype(length))).object();
}
#endif

namespace {
constexpr qint64 inputLimit = 256LL * 1024 * 1024;
constexpr HolonightImages::Limits limits{inputLimit, 64000000, 32768, inputLimit, 1024 * 1024, 64 * 1024 * 1024, 4096};
bool readExact(void* data, size_t size) { return std::fread(data, 1, size, stdin) == size; }
bool receive(QJsonObject& control, QByteArray& payload) {
  quint32 length = 0;
  if (!readExact(&length, sizeof length)) return false;
  length = qFromBigEndian(length);
  if (!length || length > 65536) return false;
  QByteArray json(length, Qt::Uninitialized);
  if (!readExact(json.data(), length)) return false;
  QJsonParseError error;
  auto document = QJsonDocument::fromJson(json, &error);
  if (error.error != QJsonParseError::NoError || !document.isObject()) return false;
  control = document.object();
  const auto bytes = control.value("bytes").toInteger(-1);
  if (bytes < 0 || bytes > inputLimit) return false;
  payload.resize(bytes);
  return readExact(payload.data(), size_t(bytes));
}
void send(QJsonObject control, QImage image = {}) {
  if (!image.isNull()) {
    control["qt_color_space_valid"] = image.colorSpace().isValid();
    control["qt_profile_present"] = !image.colorSpace().iccProfile().isEmpty();
    control["qt_color_description"] = image.colorSpace().description().left(256);
    if (image.colorSpace().isValid()) {
      image = image.convertedToColorSpace(QColorSpace::SRgb);
    }
    image.convertTo(QImage::Format_RGBA8888_Premultiplied);
    if (image.isNull() || image.width() > 32768 || image.height() > 32768 ||
        qint64(image.width()) * image.height() > limits.sourcePixels || image.sizeInBytes() > limits.decodedBytes) {
      image = {};
      control["outcome"] = "output-limit";
    }
  }
  control["width"] = image.width();
  control["height"] = image.height();
  control["stride"] = image.bytesPerLine();
  control["bytes"] = image.sizeInBytes();
  control["pixel_format"] = "RGBA8-premultiplied-sRGB";
  auto json = QJsonDocument(control).toJson(QJsonDocument::Compact);
  quint32 length = qToBigEndian(quint32(json.size()));
  std::fwrite(&length, 1, sizeof length, stdout);
  std::fwrite(json.constData(), 1, size_t(json.size()), stdout);
  if (!image.isNull()) std::fwrite(image.constBits(), 1, size_t(image.sizeInBytes()), stdout);
  std::fflush(stdout);
}
QJsonObject facts(const HolonightImages::MetadataResult& metadata) {
  const auto& f = metadata.facts;
  QJsonObject o{{"outcome", int(metadata.outcome)}, {"make", f.make}, {"model", f.model}, {"lens", f.lens}};
  auto number = [&o](const char* key, auto value) {
    if (value) o[key] = double(*value);
  };
  number("aperture", f.aperture);
  number("exposure_seconds", f.exposureSeconds);
  number("focal_length_mm", f.focalLengthMm);
  number("iso", f.iso);
  number("latitude", f.latitude);
  number("longitude", f.longitude);
  number("altitude_meters", f.altitudeMeters);
  return o;
}
// Discovery and completed-capsule validation share the provider policy and extraction.
bool svgResources(const QByteArray& bytes, const std::atomic_bool& cancelled, QJsonArray& paths) {
  if (bytes.size() > 10 * 1024 * 1024 || cancelled.load()) return false;
  const auto inspection = HolonightImages::inspectSvg(bytes, cancelled);
  if (inspection.outcome != HolonightImages::Outcome::Success &&
      inspection.resourceReason != HolonightImages::SvgResourceReason::LocalImageReference)
    return false;
  QXmlStreamReader xml(bytes);
  while (!xml.atEnd()) {
    xml.readNext();
    if (cancelled.load()) return false;
    if (xml.tokenType() == QXmlStreamReader::DTD || xml.tokenType() == QXmlStreamReader::EntityReference) return false;
    if (!xml.isStartElement()) continue;
    for (const auto& attribute : xml.attributes()) {
      if (attribute.name() == QLatin1String("base")) return false;
      if (attribute.name() != QLatin1String("href") && attribute.name() != QLatin1String("src")) continue;
      const auto path = attribute.value().toString();
      const auto kind = HolonightImages::classifySvgReference(path);
      if (kind == HolonightImages::SvgReferenceKind::Fragment ||
          kind == HolonightImages::SvgReferenceKind::EmbeddedRaster)
        continue;
      if (xml.name() != QLatin1String("image") || kind != HolonightImages::SvgReferenceKind::LocalFile ||
          paths.size() >= 256 || path.toUtf8().size() > 1024 || path != path.trimmed() || QDir::isAbsolutePath(path) ||
          path.contains('%') || path.contains('\\') || path.contains('?') || path.contains('#') || path.contains(':') ||
          path.contains(QChar(0)))
        return false;
      for (const auto& part : path.split('/')) {
        if (part.isEmpty() || part == "." || part == "..") return false;
      }
      paths.append(path);
    }
  }
  return !xml.hasError() && QJsonDocument(QJsonObject{{"paths", paths}}).toJson(QJsonDocument::Compact).size() <= 65000;
}
bool capsuleAllowed(const QByteArray& bytes, const std::atomic_bool& cancelled) {
  QJsonArray paths;
  if (!svgResources(bytes, cancelled, paths)) return false;
  for (const auto& entry : paths) {
    const auto path = entry.toString();
    QString current = "/capsule";
    for (const auto& part : path.split('/')) {
      current += '/' + part;
      if (QFileInfo(current).isSymLink()) return false;
    }
    QFile file(current);
    if (!file.open(QIODevice::ReadOnly)) return false;
    const auto info = HolonightImages::inspect(file, limits, cancelled);
    if (info.outcome != HolonightImages::Outcome::Success ||
        !QList<QByteArray>{"png", "jpeg", "bmp", "tiff", "webp", "gif"}.contains(info.format))
      return false;
    file.seek(0);
    QImageReader reader(&file);
    if (reader.supportsAnimation()) return false;
  }
  return true;
}
}  // namespace

int main(int argc, char** argv) {
  QCoreApplication application(argc, argv);
  QImageReader::setAllocationLimit(256);
  std::atomic_bool cancelled{false};
  QByteArray snapshot;
  QBuffer buffer(&snapshot);
  std::unique_ptr<QImageReader> gif;
  bool ignoreOrientation = false;
  QJsonObject inspection;
  QJsonObject loopFact;
  int frames = 0;
  int count = 0;
  QJsonObject request;
  QByteArray payload;
#ifdef WITH_GLYCIN
  std::unique_ptr<void, decltype(&comparison_free)> session(comparison_new(), comparison_free);
  if (!session) return 3;
#endif
  while (receive(request, payload)) {
    auto operation = request.value("op").toString();
    if (operation == "close") {
      send({{"outcome", "closed"}});
      return 0;
    }
    if (operation != "load" && request.contains("ignore_orientation") &&
        request.value("ignore_orientation").toBool() != ignoreOrientation) {
      send({{"outcome", "orientation-policy-conflict"}});
      continue;
    }
    if (operation == "load") {
      ignoreOrientation = request.value("ignore_orientation").toBool();
      loopFact = gifLoopFact(payload);
    }
    if (operation == "svg-resources") {
      QJsonArray paths;
      if (svgResources(payload, cancelled, paths))
        send({{"outcome", "resources"}, {"paths", paths}});
      else
        send({{"outcome", "resource-rejected"}});
      continue;
    }
    if (operation == "gif-scan") {
      send({{"outcome", "scanned"}, {"intrinsic_loop", loopFact}});
      continue;
    }
#ifdef WITH_GLYCIN
    if (operation == "load" || operation == "restart") {
      if (operation == "load") snapshot = payload;
      session.reset(comparison_new());
      if (!session) return 3;
      if (request.value("capsule").toBool()) {
        QFile main("/capsule/main.svg");
        if (snapshot.size() > 10 * 1024 * 1024 || !main.open(QIODevice::ReadOnly) ||
            main.read(10 * 1024 * 1024 + 1) != snapshot || !capsuleAllowed(snapshot, cancelled)) {
          send({{"outcome", "resource-rejected"}});
          continue;
        }
      }
      comparison_load(session.get(), reinterpret_cast<const unsigned char*>(snapshot.constData()),
                      size_t(snapshot.size()), request.value("capsule").toBool(),
                      ignoreOrientation);
      auto control = bridgeControl(session.get());
      size_t length = 0;
      const auto* exif = comparison_result(session.get(), &length, true);
      if (control.value("outcome") == "loaded" && length <= 1024 * 1024) {
        HolonightImages::MetadataResult metadata;
        QByteArray raw(reinterpret_cast<const char*>(exif), qsizetype(length));
        // Loader metadata is TIFF bytes; libexif's provider entry expects the APP1 signature.
        if (raw.startsWith("II") || raw.startsWith("MM")) raw.prepend(QByteArray("Exif\0\0", 6));
        metadata.facts = HolonightImages::parseExif(raw);
        control["exif"] = facts(metadata);
      }
      control["intrinsic_loop"] = loopFact;
      inspection = control;
      send(control);
      continue;
    }
    if (operation == "inspect") {
      send(inspection);
      continue;
    }
    if (operation == "decode" || operation == "svg" || operation == "frame") {
      comparison_frame(session.get(), unsigned(request.value("width").toInt(32)),
                       unsigned(request.value("height").toInt(32)));
      auto control = bridgeControl(session.get());
      size_t length = 0;
      const auto* bytes = comparison_result(session.get(), &length, true);
      QImage image;
      const auto format = control.value("memory_format").toString();
      QImage::Format qtFormat = QImage::Format_Invalid;
      int channels = 4;
      if (format == "R8g8b8a8Premultiplied")
        qtFormat = QImage::Format_RGBA8888_Premultiplied;
      else if (format == "R8g8b8a8")
        qtFormat = QImage::Format_RGBA8888;
      else if (format == "R8g8b8") {
        qtFormat = QImage::Format_RGB888;
        channels = 3;
      }
      const qint64 width = control.value("width").toInteger();
      const qint64 height = control.value("height").toInteger();
      const qint64 stride = control.value("stride").toInteger();
      if (control.value("outcome") == "success") {
        if (control.value("color_state") != "Srgb" || qtFormat == QImage::Format_Invalid || width <= 0 || height <= 0 ||
            width > 32768 || height > 32768 || width * height > 64000000 || stride < width * channels ||
            stride > inputLimit || stride * height != qint64(length) || length > size_t(inputLimit)) {
          control["outcome"] = "unsupported-color-or-layout";
        } else {
          image = QImage(bytes, int(width), int(height), qsizetype(stride), qtFormat).copy();
          const QSize bound(request.value("width").toInt(32), request.value("height").toInt(32));
          if (operation == "svg" ||
              (operation == "decode" && (image.width() > bound.width() || image.height() > bound.height())))
            image = image.scaled(bound, Qt::KeepAspectRatio, Qt::SmoothTransformation);
        }
      }
      for (const auto* key : {"source_width", "source_height", "oriented_width", "oriented_height",
                              "orientation", "orientation_policy", "intrinsic_loop"})
        control[key] = inspection.value(key);
      send(control, image);
      continue;
    }
    send({{"outcome", "unsupported-operation"}});
    continue;
#endif
    if (operation == "load") {
      gif.reset();
      buffer.close();
      snapshot = std::move(payload);
      buffer.open(QIODevice::ReadOnly);
      send({{"outcome", "loaded"}, {"intrinsic_loop", loopFact}});
      continue;
    }
    if (!buffer.isOpen()) {
      send({{"outcome", "no-session"}});
      continue;
    }
    const QSize bound(request.value("width").toInt(32), request.value("height").toInt(32));
    if (bound.width() <= 0 || bound.height() <= 0 || bound.width() > 32768 || bound.height() > 32768) {
      send({{"outcome", "invalid-bound"}});
      continue;
    }
    if (operation == "restart" && !snapshot.startsWith("GIF")) operation = "inspect";
    if (operation == "gif-open" || operation == "restart") {
      gif.reset();
      buffer.seek(0);
      gif = std::make_unique<QImageReader>(&buffer, "gif");
      frames = 0;
      count = gif->imageCount();
      send({{"outcome", gif->canRead() ? "success" : "damaged"},
            {"frame_count", count},
            {"loop_count", gif->loopCount()},
            {"intrinsic_loop", loopFact}});
    } else if (operation == "frame" && gif) {
      auto image = gif->read();
      const int delay = gif->nextImageDelay();
      const bool end = image.isNull() && count > 0 && frames >= count;
      if (!image.isNull()) ++frames;
      send({{"outcome", image.isNull() ? (end ? "end" : "damaged") : "success"}, {"delay_ms", delay}}, image);
    } else if (operation == "svg") {
      auto source = HolonightImages::loadSvg(buffer, 10 * 1024 * 1024, cancelled);
      if (request.value("capsule").toBool()) {
        QFile main("/capsule/main.svg");
        if (!main.open(QIODevice::ReadOnly) || main.read(10 * 1024 * 1024 + 1) != source.bytes ||
            !capsuleAllowed(source.bytes, cancelled)) {
          send({{"outcome", "resource-rejected"}});
          continue;
        }
        QSvgRenderer renderer;
        renderer.setOptions(QtSvg::Option::DisableAnimations);
        if (!renderer.load(QStringLiteral("/capsule/main.svg"))) {
          send({{"outcome", "damaged"}});
          continue;
        }
        const auto size = HolonightImages::svgPixelSize(
            HolonightImages::svgDocumentSize(renderer.defaultSize(), renderer.viewBoxF()), bound);
        if (size.isEmpty() || qint64(size.width()) * size.height() > 64000000) {
          send({{"outcome", "output-limit"}});
          continue;
        }
        QImage image(size, QImage::Format_RGBA8888_Premultiplied);
        image.fill(Qt::transparent);
        QPainter painter(&image);
        renderer.render(&painter);
        painter.end();
        send({{"outcome", "success"}}, image);
        continue;
      }
      auto result = HolonightImages::rasterizeSvg(source.bytes, {bound, inputLimit}, cancelled);
      send({{"outcome", int(result.inspection.outcome)}, {"resource_reason", int(result.inspection.resourceReason)}},
           result.image);
    } else if (operation == "decode" || operation == "inspect" || operation == "metadata") {
      gif.reset();
      const auto orientation = ignoreOrientation ? HolonightImages::OrientationPolicy::Ignore
                                                 : HolonightImages::OrientationPolicy::Apply;
      if (operation == "metadata") {
        send({{"outcome", "metadata"}, {"metadata", facts(HolonightImages::readMetadata(buffer, limits, cancelled))}});
        continue;
      }
      auto inspection = HolonightImages::inspect(buffer, limits, cancelled, orientation);
      QJsonObject result{{"outcome", int(inspection.outcome)},
                         {"format", QString::fromLatin1(inspection.format)},
                         {"source_width", inspection.sourceSize.width()},
                         {"source_height", inspection.sourceSize.height()},
                         {"oriented_width", inspection.orientedSize.width()},
                         {"oriented_height", inspection.orientedSize.height()},
                         {"metadata", facts(inspection.metadata)}};
      // Qt transformations are bit flags, not EXIF values.
      constexpr int exifOrientation[] = {1, 2, 4, 3, 6, 7, 5, 8};
      result["orientation"] = exifOrientation[int(inspection.orientation) & 7];
      result["orientation_policy"] = ignoreOrientation ? "Ignore" : "Apply";
      result["intrinsic_loop"] = loopFact;
      QImage image;
      if (operation == "decode") {
        auto decoded = HolonightImages::decode(buffer, {limits, bound, orientation}, cancelled);
        result["outcome"] = int(decoded.outcome);
        image = std::move(decoded.image);
      }
      send(result, image);
    } else {
      send({{"outcome", "unsupported-operation"}});
    }
  }
  return 2;  // EOF, malformed control or short payload: no fallback.
}
