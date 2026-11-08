// SPDX-License-Identifier: GPL-3.0-or-later
#include <QBuffer>
#include <QColorSpace>
#include <QCoreApplication>
#include <QDir>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>

#include <array>
#include <cstdio>
#include <holonight_images/isolated.h>
#include <print>
#include <stdexcept>
using namespace HolonightImages;
namespace {
const Limits limits{.inputBytes = 256 * 1024 * 1024,
                    .sourcePixels = 32000000,
                    .sourceExtent = 32768,
                    .decodedBytes = 128 * 1024 * 1024,
                    .metadataBytes = 1024 * 1024,
                    .tiffMetadataBytes = 64 * 1024 * 1024,
                    .metadataRecords = 4096};
const std::atomic_bool running{false};
void require(bool value, const char* message) {
  if (!value) {
    throw std::runtime_error(message);
  }
}
void compare(const QImage& directValue, const QImage& isolatedValue) {
  require(directValue == isolatedValue, "pixel mismatch");
  require(directValue.format() == isolatedValue.format(), "format mismatch");
  require(directValue.colorSpace() == isolatedValue.colorSpace(), "color mismatch");
  require(directValue.colorTable() == isolatedValue.colorTable(), "palette mismatch");
  require(directValue.textKeys() == isolatedValue.textKeys(), "text keys mismatch");
  for (const auto& key : directValue.textKeys()) {
    require(directValue.text(key) == isolatedValue.text(key), "text mismatch");
  }
  require(directValue.offset() == isolatedValue.offset() &&
              directValue.dotsPerMeterX() == isolatedValue.dotsPerMeterX() &&
              directValue.dotsPerMeterY() == isolatedValue.dotsPerMeterY() &&
              directValue.devicePixelRatio() == isolatedValue.devicePixelRatio(),
          "image metadata mismatch");
}
}  // namespace
// Keep the installed-package acceptance matrix together.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  const auto arguments = QCoreApplication::arguments();
  try {
    require(argc == 3, "runtime and fixtures required");
    IsolatedClient client(arguments[1]);
    qint64 total = 0;
    qint64 peak = 0;
    qint64 startup = 0;
    qint64 operation = 0;
    int operations = 0;
    auto check = [&](QByteArray bytes, const DecodeOptions& options) {
      QBuffer buffer(&bytes);
      buffer.open(QIODevice::ReadOnly);
      const auto direct = decode(buffer, options, running);
      const auto isolated = client.decode(buffer, options, running);
      if (isolated.runtime != RuntimeStatus::Success) {
        std::println(stderr, "runtime {}: {}", static_cast<int>(isolated.runtime), qPrintable(isolated.diagnostic));
      }
      require(isolated.runtime == RuntimeStatus::Success && isolated.result.has_value(), "isolated runtime failed");
      require(buffer.isOpen(), "caller device closed");
      require(isolated.result->outcome == direct.outcome, "outcome mismatch");
      compare(isolated.result->image, direct.image);
      total += isolated.elapsedMilliseconds;
      startup += isolated.startupMilliseconds;
      operation += isolated.operationMilliseconds;
      peak = qMax(peak, isolated.peakMemoryBytes);
      ++operations;
      return isolated.result->image;
    };
    for (const auto* name : {"sample.png", "sample.bmp", "sample.gif", "sample.webp", "sample.tif", "sample.jpg"}) {
      QFile file(arguments[2] + "/" + name);
      require(file.open(QIODevice::ReadOnly), "fixture missing");
      auto bytes = file.readAll();
      auto image = check(bytes, {.limits = limits, .bound = {}});
      if (QByteArray(name) != "sample.jpg") {
        require(image.size() == QSize(1, 1) && image.pixelColor(0, 0).red() == 255, "independent red pixel");
        if (QByteArray(name) == "sample.png" || QByteArray(name) == "sample.webp" || QByteArray(name) == "sample.tif") {
          require(image.pixelColor(0, 0).alpha() == 128, "independent alpha");
        }
      }
      for (auto orientation : {OrientationPolicy::Apply, OrientationPolicy::Ignore}) {
        check(bytes, {.limits = limits, .bound = {5, 8}, .orientation = orientation});
        check(bytes, {.limits = limits, .bound = {100, 100}, .orientation = orientation});
        QBuffer buffer(&bytes);
        buffer.open(QIODevice::ReadOnly);
        auto directValue = inspect(buffer, limits, running, orientation);
        auto isolatedValue = client.inspect(buffer, limits, running, orientation).result;
        require(isolatedValue && directValue.outcome == isolatedValue->outcome &&
                    directValue.sourceSize == isolatedValue->sourceSize &&
                    directValue.orientedSize == isolatedValue->orientedSize &&
                    directValue.orientation == isolatedValue->orientation &&
                    directValue.format == isolatedValue->format &&
                    directValue.metadata.facts == isolatedValue->metadata.facts,
                "inspection mismatch");
        const auto metadataResult = client.readMetadata(buffer, limits, running);
        const auto direct = readMetadata(buffer, limits, running);
        require(metadataResult.result && metadataResult.result->outcome == direct.outcome &&
                    metadataResult.result->facts == direct.facts,
                "metadata mismatch");
      }
    }
    {
      QFile file(arguments[2] + "/sample.jpg");
      require(file.open(QIODevice::ReadOnly), "orientation fixture");
      const auto original = file.readAll();
      const auto field = original.indexOf(QByteArray::fromHex("120103000100000006000000"));
      require(field >= 0, "orientation tag not found");
      for (int orientation = 1; orientation <= 8; ++orientation) {
        auto bytes = original;
        bytes[field + 8] = static_cast<char>(orientation);
        auto applied = check(bytes, {.limits = limits, .bound = {}});
        auto ignored = check(bytes, {.limits = limits, .bound = {}, .orientation = OrientationPolicy::Ignore});
        require(ignored.size() == QSize(40, 20), "independent stored size");
        require(applied.size() == (orientation >= 5 ? QSize(20, 40) : QSize(40, 20)), "independent oriented size");
        const std::array<QPoint, 8> corner = {{{0, 0}, {39, 0}, {39, 19}, {0, 19}, {0, 0}, {0, 19}, {39, 19}, {39, 0}}};
        require(applied.pixelColor(0, 0) == ignored.pixelColor(corner.at(orientation - 1)),
                "independent orientation corner");
        check(bytes, {.limits = limits, .bound = {5, 8}});
        check(bytes, {.limits = limits, .bound = {5, 8}, .orientation = OrientationPolicy::Ignore});
      }
    }
    {
      QFile file(arguments[2] + "/sample.jpg");
      require(file.open(QIODevice::ReadOnly), "limit fixture");
      const auto bytes = file.readAll();
      for (int policy = 0; policy < 5; ++policy) {
        auto bounded = limits;
        if (policy == 0) {
          bounded.inputBytes = 1;
        }
        if (policy == 1) {
          bounded.sourcePixels = 1;
        }
        if (policy == 2) {
          bounded.sourceExtent = 1;
        }
        if (policy == 3) {
          bounded.decodedBytes = 1;
        }
        if (policy == 4) {
          bounded.metadataBytes = 1;
        }
        check(bytes, {.limits = bounded, .bound = {}});
      }
    }
    // Every deterministic raster fixture, including malformed TIFF and metadata budgets.
    for (const auto& name :
         QDir(arguments[2]).entryList({"*.png", "*.tif", "*.bmp", "*.webp", "*.jpg", "*.gif"}, QDir::Files)) {
      QFile file(arguments[2] + "/" + name);
      require(file.open(QIODevice::ReadOnly), "fixture missing");
      check(file.readAll(), {.limits = limits, .bound = {}});
    }
    for (auto format : {QImage::Format_RGBA64, QImage::Format_Grayscale16, QImage::Format_Indexed8}) {
      QImage image(3, 2, format);
      image.fill(0);
      if (format == QImage::Format_Indexed8) {
        image.setColorTable({qRgba(12, 34, 56, 78)});
      } else {
        image.setPixelColor(1, 1, QColor::fromRgba64(12345, 23456, 34567, 45678));
      }
      for (int color = 0; color <= QColorSpace::Bt2100Hlg; ++color) {
        image.setColorSpace((color != 0) ? QColorSpace(QColorSpace::NamedColorSpace(color)) : QColorSpace());
        QByteArray bytes;
        QBuffer output(&bytes);
        output.open(QIODevice::WriteOnly);
        require(image.save(&output, "PNG"), "precision fixture encoding failed");
        check(bytes, {.limits = limits, .bound = {}});
      }
    }
    QImage custom(1, 1, QImage::Format_RGBA64);
    custom.fill(Qt::red);
    custom.setColorSpace(QColorSpace(QColorSpace::Primaries::SRgb, QColorSpace::TransferFunction::Gamma, 1.7));
    QByteArray encoded;
    QBuffer output(&encoded);
    output.open(QIODevice::ReadWrite);
    require(custom.save(&output, "PNG"), "custom profile encode");
    auto unsupported = client.decode(output, {.limits = limits, .bound = {}}, running);
    require(
        unsupported.result && unsupported.result->outcome == Outcome::Unsupported && unsupported.result->image.isNull(),
        "custom profile not explicitly rejected");
    QBuffer svg;
    svg.setData("<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>");
    svg.open(QIODevice::ReadOnly);
    auto excluded = client.decode(svg, {.limits = limits, .bound = {}}, running);
    require(excluded.result && excluded.result->outcome == Outcome::Unsupported, "SVG accepted");
    std::puts(QJsonDocument(QJsonObject{{"decodeOperations", operations},
                                        {"decodeTotalMs", total},
                                        {"startupTotalMs", startup},
                                        {"operationTotalMs", operation},
                                        {"peakScopeMemoryBytes", peak}})
                  .toJson(QJsonDocument::Compact)
                  .constData());
    return 0;
  } catch (const std::exception& e) {
    std::println(stderr, "{}", e.what());
    return 1;
  }
}
