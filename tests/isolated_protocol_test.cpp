// SPDX-License-Identifier: GPL-3.0-or-later
#include "../src/isolated/protocol.h"

#include <QColorSpace>
#include <QJsonArray>

#include <gtest/gtest.h>
using namespace HolonightImages;
using namespace HolonightImages::Isolation;
namespace {
const Request request{.operation = Operation::Decode,
                      .options = {.limits = {.inputBytes = 1048576,
                                             .sourcePixels = 100000,
                                             .sourceExtent = 1000,
                                             .decodedBytes = 1048576,
                                             .metadataBytes = 1024,
                                             .tiffMetadataBytes = 1024,
                                             .metadataRecords = 100},
                                  .bound = {},
                                  .orientation = OrientationPolicy::Apply},
                      .metadata = true};
Reply source(QImage image) {
  Reply reply;
  reply.decoded.image = std::move(image);
  reply.decoded.inspection.sourceSize = reply.decoded.image.size();
  reply.decoded.inspection.orientedSize = reply.decoded.image.size();
  return reply;
}
}  // namespace
TEST(IsolatedProtocol, PreservesAllSupportedFormatsAndMetadata) {
  for (int format = 1; format < QImage::NImageFormats; ++format) {
    if (pixelDepth(format) == 0) {
      continue;
    }
    QImage image(3, 2, QImage::Format(format));
    image.fill(0);
    if (image.depth() == 1) {
      image.setColorTable({qRgba(1, 2, 3, 4), qRgba(5, 6, 7, 8)});
    }
    if (format == QImage::Format_Indexed8) {
      image.setColorTable({qRgba(12, 34, 56, 78)});
    }
    image.setDotsPerMeterX(1234);
    image.setDotsPerMeterY(5678);
    image.setOffset({-7, 11});
    image.setDevicePixelRatio(2.5);
    image.setText("author", "example");
    for (int color = 0; color <= QColorSpace::Bt2100Hlg; ++color) {
      image.setColorSpace((color != 0) ? QColorSpace(QColorSpace::NamedColorSpace(color)) : QColorSpace());
      auto reply = source(image);
      QByteArray pixels;
      auto control = replyControl(reply, Operation::Decode, pixels);
      auto output = parseReply(control, pixels, request).decoded.image;
      ASSERT_EQ(output, image) << format << "/" << color;
      EXPECT_EQ(output.format(), image.format());
      EXPECT_EQ(output.colorTable(), image.colorTable());
      EXPECT_EQ(output.colorSpace(), image.colorSpace());
      EXPECT_EQ(output.offset(), image.offset());
      EXPECT_EQ(output.devicePixelRatio(), 2.5);
      EXPECT_EQ(output.dotsPerMeterX(), 1234);
      EXPECT_EQ(output.dotsPerMeterY(), 5678);
      EXPECT_EQ(output.text("author"), "example");
    }
  }
}
TEST(IsolatedProtocol, RejectsCustomColorWithoutConversion) {
  QImage image(1, 1, QImage::Format_RGBA64);
  image.fill(Qt::red);
  image.setColorSpace(QColorSpace(QColorSpace::Primaries::SRgb, QColorSpace::TransferFunction::Gamma, 1.7));
  ASSERT_TRUE(image.colorSpace().isValid());
  auto reply = source(image);
  QByteArray pixels;
  auto control = replyControl(reply, Operation::Decode, pixels);
  const auto output = parseReply(control, pixels, request).decoded;
  EXPECT_EQ(output.outcome, Outcome::Unsupported);
  EXPECT_TRUE(output.image.isNull());
  EXPECT_TRUE(pixels.isEmpty());
}
TEST(IsolatedProtocol, RejectsMalformedLayoutsWithoutPartialImage) {
  QImage image(3, 2, QImage::Format_RGBA64);
  image.fill(Qt::red);
  auto reply = source(image);
  QByteArray pixels;
  const auto original = replyControl(reply, Operation::Decode, pixels);
  for (const auto* key : {"version", "operation", "bytes", "width", "height", "stride", "format", "color", "dpr",
                          "palette", "text", "inspection", "outcome"}) {
    auto record = original;
    record.remove(key);
    EXPECT_THROW(parseReply(record, pixels, request), ProtocolError) << key;
    record = original;
    record[key] = -100;
    EXPECT_THROW(parseReply(record, pixels, request), ProtocolError) << key;
    record = original;
    record[key] = 1e30;
    EXPECT_THROW(parseReply(record, pixels, request), ProtocolError) << key;
  }
  auto inconsistent = original;
  auto inspection = inconsistent["inspection"].toObject();
  inspection["outcome"] = static_cast<int>(Outcome::ResourceLimit);
  inconsistent["inspection"] = inspection;
  EXPECT_THROW(parseReply(inconsistent, pixels, request), ProtocolError);
  EXPECT_THROW(parseReply(original, pixels.first(pixels.size() - 1), request), ProtocolError);
  auto limited = request;
  limited.options.limits.decodedBytes = pixels.size() - 1;
  EXPECT_THROW(parseReply(original, pixels, limited), ProtocolError);
  limited = request;
  limited.options.bound = {1, 1};
  EXPECT_THROW(parseReply(original, pixels, limited), ProtocolError);
  EXPECT_THROW(parseControl("{} garbage"), ProtocolError);
}
TEST(IsolatedProtocol, StructuredMetadataRoundTrip) {
  Reply reply;
  reply.metadata.facts = {.make = "make",
                          .model = "model",
                          .lens = "lens",
                          .aperture = 1.4,
                          .exposureSeconds = 0.003,
                          .focalLengthMm = 45.0,
                          .iso = 400,
                          .latitude = 50.25,
                          .longitude = -30.125,
                          .altitudeMeters = 42.5};
  QByteArray pixels;
  auto control = replyControl(reply, Operation::Metadata, pixels);
  auto metadataRequest = request;
  metadataRequest.operation = Operation::Metadata;
  EXPECT_EQ(parseReply(control, pixels, metadataRequest).metadata.facts, reply.metadata.facts);
}
