#include "device.h"

#include <QtEndian>

#include <cmath>
#include <cstring>
#include <holonight_images/image.h>
#include <libexif/exif-data.h>
#include <libexif/exif-log.h>
#include <memory>
#include <optional>
#include <span>

namespace HolonightImages {
namespace {
const QByteArray exif_header("Exif\0\0", 6);

using ExifDataPtr = std::unique_ptr<ExifData, decltype(&exif_data_unref)>;
using ExifLogPtr = std::unique_ptr<ExifLog, decltype(&exif_log_unref)>;

// libexif reports malformed blocks on stderr by default; damaged metadata is not an error here.
void silentLog(ExifLog* /*log*/, ExifLogCode /*code*/, const char* /*domain*/, const char* /*format*/, va_list /*args*/,
               void* /*data*/) {}

std::optional<QByteArray> readExactly(QIODevice& source, qint64 length) {
  auto bytes = source.read(length);
  return bytes.size() == length ? std::optional{std::move(bytes)} : std::nullopt;
}

bool skip(QIODevice& source, qint64 length) {
  return length >= 0 && length <= source.size() - source.pos() && source.seek(source.pos() + length);
}

// Oversized blocks are skipped, not truncated, so libexif never sees partial offsets.
QByteArray block(QIODevice& source, qint64 length, const Limits& limits, Outcome& outcome) {
  if (length <= 0 || length > limits.metadataBytes) {
    outcome = length > limits.metadataBytes ? Outcome::ResourceLimit : Outcome::Damaged;
    return {};
  }
  return readExactly(source, length).value_or(QByteArray{});
}

QByteArray jpegPayload(QIODevice& source, const std::atomic_bool& cancelled, const Limits& limits, Outcome& outcome) {
  for (int records = 0; records < limits.metadataRecords && !cancelled.load(); ++records) {
    const auto marker = readExactly(source, 2);
    if (!marker || static_cast<unsigned char>(marker->at(0)) != 0xff) {
      return {};
    }
    const auto code = static_cast<unsigned char>(marker->at(1));
    if (code == 0xff) {
      source.seek(source.pos() - 1);  // Fill byte before the real marker code.
      continue;
    }
    if (code == 0xd9 || code == 0xda) {
      return {};  // Metadata segments precede the scan.
    }
    if ((code >= 0xd0 && code <= 0xd7) || code == 0x01) {
      continue;
    }
    const auto length = readExactly(source, 2);
    if (!length) {
      return {};
    }
    const qint64 size = qFromBigEndian<quint16>(length->constData()) - 2;
    if (size < 0) {
      return {};
    }
    if (code == 0xe1 && size >= exif_header.size() && source.peek(exif_header.size()) == exif_header) {
      return block(source, size, limits, outcome);  // XMP and other APP1 segments are skipped below.
    }
    if (!skip(source, size)) {
      return {};
    }
  }
  return {};
}

QByteArray pngPayload(QIODevice& source, const std::atomic_bool& cancelled, const Limits& limits, Outcome& outcome) {
  for (int records = 0; records < limits.metadataRecords && !cancelled.load(); ++records) {
    const auto header = readExactly(source, 8);
    if (!header) {
      return {};
    }
    const qint64 length = qFromBigEndian<quint32>(header->constData());
    const auto type = header->sliced(4);
    if (type == "IEND") {
      return {};
    }
    if (type == "eXIf") {
      const auto data = block(source, length, limits, outcome);
      return data.isEmpty() ? QByteArray{} : exif_header + data;
    }
    if (!skip(source, length + 4)) {  // Chunk data and CRC.
      return {};
    }
  }
  return {};
}

QByteArray webpPayload(QIODevice& source, const std::atomic_bool& cancelled, const Limits& limits, Outcome& outcome) {
  for (int records = 0; records < limits.metadataRecords && !cancelled.load(); ++records) {
    const auto header = readExactly(source, 8);
    if (!header) {
      return {};
    }
    const qint64 length = qFromLittleEndian<quint32>(header->sliced(4).constData());
    if (header->first(4) == "EXIF") {
      const auto data = block(source, length, limits, outcome);
      // Some writers store the TIFF block without the JPEG-style signature.
      return data.isEmpty() || data.startsWith(exif_header) ? data : exif_header + data;
    }
    if (!skip(source, length + (length & 1))) {
      return {};
    }
  }
  return {};
}

// Compares raw tag numbers: GPS tags share values with interoperability tags and are not ExifTag enumerators.
ExifEntry* entry(ExifData* data, ExifIfd ifd, quint16 tag) {
  const auto* content = std::span<ExifContent*, EXIF_IFD_COUNT>(data->ifd)[ifd];
  if (content == nullptr || content->entries == nullptr) {
    return nullptr;
  }
  for (auto* item : std::span(content->entries, content->count)) {
    if (item != nullptr && static_cast<quint16>(item->tag) == tag) {
      return item;
    }
  }
  return nullptr;
}

QString ascii(ExifData* data, ExifIfd ifd, quint16 tag) {
  const auto* item = entry(data, ifd, tag);
  if (item == nullptr || item->format != EXIF_FORMAT_ASCII || item->data == nullptr) {
    return {};
  }
  const auto* text = static_cast<const char*>(static_cast<const void*>(item->data));
  return QString::fromUtf8(text, static_cast<qsizetype>(strnlen(text, item->size))).simplified();
}

std::optional<double> rational(ExifData* data, ExifIfd ifd, quint16 tag, unsigned int index = 0) {
  const auto* item = entry(data, ifd, tag);
  const auto width = exif_format_get_size(EXIF_FORMAT_RATIONAL);
  if (item == nullptr || item->format != EXIF_FORMAT_RATIONAL || item->data == nullptr || item->components <= index ||
      item->size < width * (index + 1)) {
    return std::nullopt;
  }
  const auto value = exif_get_rational(std::span(item->data, item->size).subspan(width * index).data(),
                                       exif_data_get_byte_order(data));
  if (value.denominator == 0) {
    return std::nullopt;
  }
  return static_cast<double>(value.numerator) / value.denominator;
}

std::optional<quint32> integer(ExifData* data, ExifIfd ifd, quint16 tag) {
  const auto* item = entry(data, ifd, tag);
  if (item == nullptr || item->data == nullptr || item->components == 0) {
    return std::nullopt;
  }
  const auto order = exif_data_get_byte_order(data);
  if (item->format == EXIF_FORMAT_BYTE && item->size >= 1) {
    return *item->data;
  }
  if (item->format == EXIF_FORMAT_SHORT && item->size >= 2) {
    return exif_get_short(item->data, order);
  }
  if (item->format == EXIF_FORMAT_LONG && item->size >= 4) {
    return exif_get_long(item->data, order);
  }
  return std::nullopt;
}

std::optional<double> coordinate(ExifData* data, quint16 value, double limit) {
  const auto degrees = rational(data, EXIF_IFD_GPS, value, 0);
  const auto minutes = rational(data, EXIF_IFD_GPS, value, 1);
  const auto seconds = rational(data, EXIF_IFD_GPS, value, 2);
  if (!degrees || !minutes || !seconds) {
    return std::nullopt;
  }
  const auto result = *degrees + (*minutes / 60) + (*seconds / 3600);
  return std::isfinite(result) && result <= limit ? std::optional{result} : std::nullopt;
}

// Oversized files are skipped, not truncated, for the same reason as oversized blocks. BigTIFF is not matched.
QByteArray tiffPayload(QIODevice& source, const std::atomic_bool& cancelled, const Limits& limits, Outcome& outcome) {
  if (source.size() > limits.tiffMetadataBytes) {
    outcome = Outcome::ResourceLimit;
    return {};
  }
  if (!source.seek(0)) {
    return {};
  }
  QByteArray data = exif_header;
  data.reserve(exif_header.size() + source.size());
  while (!source.atEnd()) {
    const auto part = source.read(qint64{1024 * 1024});
    if (part.isEmpty() || cancelled.load()) {
      return {};
    }
    data += part;
  }
  return data;
}
}  // namespace

QByteArray payload(QIODevice& source, const std::atomic_bool& cancelled, const Limits& limits, Outcome& outcome) {
  if (source.isSequential() || !source.seek(0)) {
    return {};
  }
  auto signature = source.read(2);
  if (signature == QByteArray("\xff\xd8", 2)) return jpegPayload(source, cancelled, limits, outcome);
  signature += source.read(6);
  if (signature == QByteArray("\x89PNG\r\n\x1a\n", 8)) return pngPayload(source, cancelled, limits, outcome);
  if (signature.startsWith("RIFF")) {
    signature += source.read(4);
    if (signature.size() == 12 && signature.sliced(8) == "WEBP") return webpPayload(source, cancelled, limits, outcome);
  }
  if (signature.startsWith(QByteArray("II*\0", 4)) || signature.startsWith(QByteArray("MM\0*", 4))) {
    return tiffPayload(source, cancelled, limits, outcome);
  }
  return {};
}

ExifFacts parseExif(const QByteArray& payload) {
  if (payload.isEmpty()) {
    return {};
  }
  const ExifDataPtr data(exif_data_new(), exif_data_unref);
  if (!data) {
    return {};
  }
  const ExifLogPtr log(exif_log_new(), exif_log_unref);
  if (log) {
    exif_log_set_func(log.get(), &silentLog, nullptr);
    exif_data_log(data.get(), log.get());
  }
  exif_data_load_data(data.get(), static_cast<const unsigned char*>(static_cast<const void*>(payload.constData())),
                      static_cast<unsigned int>(payload.size()));
  ExifFacts facts;
  facts.make = ascii(data.get(), EXIF_IFD_0, EXIF_TAG_MAKE);
  facts.model = ascii(data.get(), EXIF_IFD_0, EXIF_TAG_MODEL);
  facts.lens = ascii(data.get(), EXIF_IFD_EXIF, EXIF_TAG_LENS_MODEL);
  facts.aperture = rational(data.get(), EXIF_IFD_EXIF, EXIF_TAG_FNUMBER);
  facts.exposureSeconds = rational(data.get(), EXIF_IFD_EXIF, EXIF_TAG_EXPOSURE_TIME);
  facts.focalLengthMm = rational(data.get(), EXIF_IFD_EXIF, EXIF_TAG_FOCAL_LENGTH);
  facts.iso = integer(data.get(), EXIF_IFD_EXIF, EXIF_TAG_ISO_SPEED_RATINGS);
  auto latitude = coordinate(data.get(), EXIF_TAG_GPS_LATITUDE, 90);
  auto longitude = coordinate(data.get(), EXIF_TAG_GPS_LONGITUDE, 180);
  const auto latRef = ascii(data.get(), EXIF_IFD_GPS, EXIF_TAG_GPS_LATITUDE_REF).toUpper();
  const auto lonRef = ascii(data.get(), EXIF_IFD_GPS, EXIF_TAG_GPS_LONGITUDE_REF).toUpper();
  if (latitude && longitude && (latRef == "N" || latRef == "S") && (lonRef == "E" || lonRef == "W")) {
    facts.latitude = latRef == "S" ? -*latitude : *latitude;
    facts.longitude = lonRef == "W" ? -*longitude : *longitude;
  }
  auto altitude = rational(data.get(), EXIF_IFD_GPS, EXIF_TAG_GPS_ALTITUDE);
  if (altitude)
    facts.altitudeMeters =
        integer(data.get(), EXIF_IFD_GPS, EXIF_TAG_GPS_ALTITUDE_REF).value_or(0) == 1 ? -*altitude : *altitude;
  return facts;
}

MetadataResult readMetadata(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled) {
  if (cancelled.load()) return {Outcome::Cancelled, {}};
  if (!source.isOpen() || !source.isReadable() || source.isSequential() || !source.seek(0))
    return {Outcome::IoFailure, {}};
  if (!valid(limits) || source.size() > limits.inputBytes) return {Outcome::ResourceLimit, {}};
  Device device(source);
  Outcome outcome = Outcome::Success;
  const auto bytes = payload(device, cancelled, limits, outcome);
  if (cancelled.load()) return {Outcome::Cancelled, {}};
  if (device.failed) return {Outcome::IoFailure, {}};
  return {outcome, parseExif(bytes)};
}
}  // namespace HolonightImages
