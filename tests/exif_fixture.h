#pragma once

// Builds EXIF payloads and JPEG files for tests without binary fixtures.

#include <QBuffer>
#include <QByteArray>
#include <QImage>
#include <QList>
#include <QtEndian>

#include <initializer_list>
#include <utility>

namespace ExifFixture {
// Minimal little-endian TIFF writer; offsets are relative to the TIFF header.
struct Field {
  quint16 tag;
  quint16 type;
  quint32 count;
  QByteArray data;
};

inline QByteArray le16(quint16 value) {
  QByteArray bytes(2, '\0');
  qToLittleEndian(value, bytes.data());
  return bytes;
}
inline QByteArray le32(quint32 value) {
  QByteArray bytes(4, '\0');
  qToLittleEndian(value, bytes.data());
  return bytes;
}
inline Field text(quint16 tag, const QByteArray& value) {
  return {.tag = tag, .type = 2, .count = static_cast<quint32>(value.size() + 1), .data = value + '\0'};
}
inline Field byte(quint16 tag, quint8 value) {
  return {.tag = tag, .type = 1, .count = 1, .data = QByteArray(1, static_cast<char>(value))};
}
inline Field shortValue(quint16 tag, quint16 value) { return {.tag = tag, .type = 3, .count = 1, .data = le16(value)}; }
inline Field longValue(quint16 tag, quint32 value) { return {.tag = tag, .type = 4, .count = 1, .data = le32(value)}; }
inline Field rationals(quint16 tag, std::initializer_list<std::pair<quint32, quint32>> values) {
  QByteArray data;
  for (const auto& [numerator, denominator] : values) {
    data += le32(numerator) + le32(denominator);
  }
  return {.tag = tag, .type = 5, .count = static_cast<quint32>(values.size()), .data = data};
}
inline qsizetype outOfLine(const Field& field) {
  return field.data.size() > 4 ? field.data.size() + (field.data.size() & 1) : 0;
}
inline quint32 ifdSize(const QList<Field>& fields) {
  qsizetype size = 2 + (12 * fields.size()) + 4;
  for (const auto& field : fields) {
    size += outOfLine(field);
  }
  return static_cast<quint32>(size);
}
inline QByteArray ifd(quint32 offset, const QList<Field>& fields) {
  QByteArray entries = le16(static_cast<quint16>(fields.size()));
  QByteArray values;
  auto valueOffset = offset + 2 + (12 * fields.size()) + 4;
  for (const auto& field : fields) {
    entries += le16(field.tag) + le16(field.type) + le32(field.count);
    if (field.data.size() <= 4) {
      entries += field.data + QByteArray(4 - field.data.size(), '\0');
    } else {
      entries += le32(static_cast<quint32>(valueOffset + values.size()));
      values += field.data + QByteArray(field.data.size() & 1, '\0');
    }
  }
  return entries + le32(0) + values;
}

inline QByteArray tiff(const QList<Field>& primary, const QList<Field>& exif, const QList<Field>& gps) {
  const quint32 exifOffset = 8 + ifdSize(primary) + 24;
  const quint32 gpsOffset = exifOffset + ifdSize(exif);
  auto zero = primary;
  zero << longValue(0x8769, exifOffset) << longValue(0x8825, gpsOffset);
  return QByteArray("II*\0", 4) + le32(8) + ifd(8, zero) + ifd(exifOffset, exif) + ifd(gpsOffset, gps);
}

inline QByteArray sonyPayload() {
  return QByteArray("Exif\0\0", 6) +
         tiff({text(0x010f, "SONY"), text(0x0110, "ILCE-7M4")},
              {rationals(0x829a, {{1, 100}}), rationals(0x829d, {{8, 1}}), shortValue(0x8827, 100),
               rationals(0x920a, {{32, 1}}), text(0xa434, "FE 24-70mm F2.8 GM II")},
              {text(0x0001, "N"), rationals(0x0002, {{50, 1}, {27, 1}, {0, 1}}), text(0x0003, "W"),
               rationals(0x0004, {{30, 1}, {31, 1}, {12, 1}}), byte(0x0005, 0), rationals(0x0006, {{1790, 10}})});
}

inline QByteArray jpegWithApp1(const QByteArray& exif) {
  QImage image(4, 3, QImage::Format_RGB32);
  image.fill(Qt::blue);
  QByteArray jpeg;
  QBuffer buffer(&jpeg);
  buffer.open(QIODevice::WriteOnly);
  image.save(&buffer, "JPEG");
  const auto segment = [](const QByteArray& body) {
    QByteArray length(2, '\0');
    qToBigEndian(static_cast<quint16>(body.size() + 2), length.data());
    return QByteArray("\xff\xe1", 2) + length + body;
  };
  // An XMP APP1 segment first proves non-EXIF APP1 segments are skipped.
  return jpeg.first(2) + segment("http://ns.adobe.com/xap/1.0/\0<x/>") + segment(exif) + jpeg.sliced(2);
}
}  // namespace ExifFixture
