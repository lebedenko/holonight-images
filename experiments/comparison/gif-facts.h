// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QByteArray>
#include <QJsonObject>
#include <QJsonValue>

#include <optional>

// A structural scan only: never decompresses pixels or replaces decoder validation.
inline QJsonObject gifLoopFact(const QByteArray& bytes) {
  QJsonObject fact{{"provenance", "supplemental-gif-block-reader"},
                   {"scan_status", "unavailable"},
                   {"raw_declaration", QJsonValue::Null},
                   {"total_plays", QJsonValue::Null},
                   {"infinite", QJsonValue::Null}};
  auto fail = [&](const char* reason) {
    fact["reason"] = reason;
    return fact;
  };
  if (bytes.size() > 256LL * 1024 * 1024) return fail("input-limit");
  qsizetype pos = 0;
  unsigned blocks = 0;
  qsizetype extensionBytes = 0;
  std::optional<unsigned> declaration;
  auto take = [&](qsizetype n) {
    if (n > bytes.size() - pos) return false;
    pos += n;
    return true;
  };
  auto byte = [&](qsizetype offset) { return static_cast<unsigned char>(bytes[offset]); };
  if (!take(6) || (bytes.first(6) != "GIF87a" && bytes.first(6) != "GIF89a")) return fail("header");
  if (!take(7)) return fail("logical-screen-descriptor");
  if (!(byte(6) | byte(7)) || !(byte(8) | byte(9))) return fail("screen-dimensions");
  auto table = [&](unsigned packed) { return !(packed & 128) || take(3LL << ((packed & 7) + 1)); };
  if (!table(byte(10))) return fail("global-color-table");
  while (pos < bytes.size()) {
    if (++blocks > 65536) return fail("block-budget");
    const auto kind = byte(pos++);
    if (kind == 0x3b) {
      if (pos != bytes.size()) return fail("trailing-data");
      fact["scan_status"] = "complete";
      if (declaration) fact["raw_declaration"] = int(*declaration);
      fact["infinite"] = declaration && *declaration == 0;
      if (!declaration || *declaration != 0) fact["total_plays"] = declaration ? int(*declaration + 1) : 1;
      return fact;
    }
    bool extension = false;
    bool loop = false;
    unsigned label = 0;
    if (kind == 0x2c) {
      const auto descriptor = pos;
      if (!take(9)) return fail("image-descriptor");
      if (!(byte(descriptor + 4) | byte(descriptor + 5)) || !(byte(descriptor + 6) | byte(descriptor + 7)))
        return fail("image-dimensions");
      if (!table(byte(descriptor + 8))) return fail("local-color-table");
      if (!take(1)) return fail("lzw-code-size");
      if (byte(pos - 1) < 2 || byte(pos - 1) > 8) return fail("lzw-code-size");
    } else if (kind == 0x21) {
      extension = true;
      if (!take(1)) return fail("extension-label");
      label = byte(pos - 1);
    } else
      return fail("block-kind");
    unsigned index = 0;
    bool foundLoop = false;
    while (true) {
      if (++blocks > 65536) return fail("block-budget");
      if (!take(1)) return fail("subblock-length");
      const auto length = byte(pos - 1);
      if (!length) break;
      const auto start = pos;
      if (!take(length)) return fail("subblock-payload");
      if (extension && (extensionBytes += length) > 1024 * 1024) return fail("extension-budget");
      if (extension && index == 0) {
        if ((label == 0xff && length != 11) || (label == 0xf9 && length != 4) || (label == 0x01 && length != 12))
          return fail("extension-block-length");
        loop =
            label == 0xff && (bytes.mid(start, length) == "NETSCAPE2.0" || bytes.mid(start, length) == "ANIMEXTS1.0");
      } else if (loop) {
        if (index != 1 || length != 3 || byte(start) != 1) return fail("loop-block-length");
        const unsigned value = byte(start + 1) | (byte(start + 2) << 8);
        if (declaration && *declaration != value) return fail("conflicting-declarations");
        declaration = value;
        foundLoop = true;
      }
      ++index;
    }
    if (extension && ((label == 0xff || label == 0xf9 || label == 0x01) && index == 0))
      return fail("missing-extension-block");
    if (extension && label == 0xf9 && index != 1) return fail("extension-block-length");
    if (loop && !foundLoop) return fail("missing-loop-data");
  }
  return fail("missing-trailer");
}
