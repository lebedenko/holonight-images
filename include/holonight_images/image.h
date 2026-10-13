#pragma once

#include <QIODevice>
#include <QImage>
#include <QImageIOHandler>
#include <QMap>
#include <QStringList>

#include <atomic>
#include <optional>

// Public aggregate member names and enum representation are part of the installed API.
// NOLINTBEGIN(readability-identifier-naming, performance-enum-size)
namespace HolonightImages {
enum class Outcome { Success, Unsupported, Damaged, ResourceLimit, IoFailure, Cancelled };
enum class OrientationPolicy { Apply, Ignore };
// All limits must be positive. Callers choose policy, including metadata scan budgets.
struct Limits {
  qint64 inputBytes;
  qint64 sourcePixels;
  int sourceExtent;
  qint64 decodedBytes;
  qint64 metadataBytes;
  qint64 tiffMetadataBytes;
  int metadataRecords;
};
struct ExifFacts {
  QString make, model, lens;
  std::optional<double> aperture, exposureSeconds, focalLengthMm;
  std::optional<quint32> iso;
  std::optional<double> latitude, longitude, altitudeMeters;
  bool operator==(const ExifFacts&) const = default;
};
struct MetadataResult {
  Outcome outcome = Outcome::Success;
  ExifFacts facts;
};
struct Inspection {
  Outcome outcome = Outcome::Success;
  QByteArray format;
  QSize sourceSize;
  QSize orientedSize;
  QImageIOHandler::Transformations orientation;
  MetadataResult metadata;
};
// The caller must supply every policy limit; preserve aggregate initialization semantics.
struct DecodeOptions {  // NOLINT(cppcoreguidelines-pro-type-member-init)
  Limits limits;
  QSize bound;  // Empty means full resolution. Never upscale.
  OrientationPolicy orientation = OrientationPolicy::Apply;
};
struct DecodeResult {
  Outcome outcome = Outcome::Success;
  Inspection inspection;
  QImage image;
};
QByteArray canonicalFormat(QByteArray format);
QStringList supportedSuffixes();
// Exclusive device access is required for each call. Position is unspecified afterwards;
// the device stays open and owned by the caller. Each operation starts at offset zero.
Inspection inspect(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled,
                   OrientationPolicy orientation = OrientationPolicy::Apply, bool metadata = true);
DecodeResult decode(QIODevice& source, const DecodeOptions& options, const std::atomic_bool& cancelled);
MetadataResult readMetadata(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled);
ExifFacts parseExif(const QByteArray& payload);
}  // namespace HolonightImages
// NOLINTEND(readability-identifier-naming, performance-enum-size)
