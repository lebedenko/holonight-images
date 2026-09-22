#include "exif_fixture.h"

#include <QCoreApplication>
#include <QFile>
#include <QImageReader>
#include <QTemporaryDir>

#include <gtest/gtest.h>
#include <holonight_images/image.h>
using namespace HolonightImages;
namespace {
constexpr Limits limits{256 * 1024 * 1024, 32000000, 32768, 128 * 1024 * 1024, 1024 * 1024, 64 * 1024 * 1024, 4096};
const std::atomic_bool running{false};
QByteArray fixture(const char* name) {
  QFile file(QStringLiteral(FIXTURE_DIR) + '/' + name);
  EXPECT_TRUE(file.open(QIODevice::ReadOnly));
  return file.readAll();
}
DecodeResult decodeBytes(QByteArray bytes, DecodeOptions options = {.limits = limits, .bound = {}}) {
  QBuffer device(&bytes);
  device.open(QIODevice::ReadOnly);
  return decode(device, options, running);
}
MetadataResult metadata(QByteArray bytes, Limits policy = limits) {
  QBuffer device(&bytes);
  device.open(QIODevice::ReadOnly);
  return readMetadata(device, policy, running);
}
// Faults stay active once triggered, so codec retries cannot hide an I/O failure.
class ControlledBuffer : public QBuffer {
 public:
  explicit ControlledBuffer(QByteArray* bytes) : QBuffer(bytes) { open(ReadOnly | Unbuffered); }
  int reads = 0;
  int seeks = 0;
  qint64 bytesRead = 0;
  int failRead = 0;
  int failSeek = 0;
  int cancelRead = 0;
  std::atomic_bool cancelled{false};
  bool seek(qint64 offset) override {
    ++seeks;
    return (failSeek == 0 || seeks < failSeek) && QBuffer::seek(offset);
  }

 protected:
  qint64 readData(char* data, qint64 size) override {
    ++reads;
    if (failRead != 0 && reads >= failRead) return -1;
    const auto count = QBuffer::readData(data, size);
    if (count > 0) bytesRead += count;
    if (cancelRead != 0 && reads >= cancelRead) cancelled.store(true);
    return count;
  }
};
enum class Operation { Inspect, Decode, Metadata };
Outcome run(Operation operation, ControlledBuffer& device) {
  switch (operation) {
    case Operation::Inspect:
      return inspect(device, limits, device.cancelled, OrientationPolicy::Apply, false).outcome;
    case Operation::Decode: {
      const auto result = decode(device, {.limits = limits, .bound = {}}, device.cancelled);
      EXPECT_EQ(result.image.isNull(), result.outcome != Outcome::Success);
      return result.outcome;
    }
    case Operation::Metadata: {
      const auto result = readMetadata(device, limits, device.cancelled);
      if (result.outcome != Outcome::Success) EXPECT_EQ(result.facts, ExifFacts{});
      return result.outcome;
    }
  }
  return Outcome::Unsupported;
}
}  // namespace
TEST(Images, RasterFormatsAlphaAndBoundedSizes) {
  for (const auto* name : {"sample.png", "sample.bmp", "sample.gif", "sample.webp", "sample.tif", "sample.jpg"}) {
    auto result = decodeBytes(fixture(name));
    ASSERT_EQ(result.outcome, Outcome::Success) << name;
    if (QByteArray(name) != "sample.jpg") {
      EXPECT_EQ(result.image.size(), QSize(1, 1));
      EXPECT_EQ(result.image.pixelColor(0, 0).red(), 255);
    }
    if (QByteArray(name) == "sample.png" || QByteArray(name) == "sample.webp" || QByteArray(name) == "sample.tif")
      EXPECT_EQ(result.image.pixelColor(0, 0).alpha(), 128);
  }
  const auto scaled = decodeBytes(fixture("sample.jpg"), {.limits = limits, .bound = {5, 8}});
  ASSERT_EQ(scaled.outcome, Outcome::Success);
  EXPECT_EQ(scaled.image.size(), QSize(4, 8));
  EXPECT_GT(scaled.image.pixelColor(3, 1).red(), 200);
  const auto ignored =
      decodeBytes(fixture("sample.jpg"), {.limits = limits, .bound = {8, 5}, .orientation = OrientationPolicy::Ignore});
  EXPECT_EQ(ignored.image.size(), QSize(8, 4));
}
TEST(Images, InspectionDimensionsAndOrientationAreConsistent) {
  auto bytes = fixture("sample.jpg");
  QBuffer device(&bytes);
  device.open(QIODevice::ReadOnly);
  const auto info = inspect(device, limits, running);
  ASSERT_EQ(info.outcome, Outcome::Success);
  EXPECT_EQ(info.format, "jpeg");
  EXPECT_EQ(info.sourceSize, QSize(40, 20));
  EXPECT_EQ(info.orientedSize, QSize(20, 40));
  EXPECT_TRUE(info.orientation.testFlag(QImageIOHandler::TransformationRotate90));
  EXPECT_EQ(inspect(device, limits, running, OrientationPolicy::Ignore).orientedSize, QSize(40, 20));
  EXPECT_TRUE(device.isOpen());
}
TEST(Images, ExplicitResourceLimits) {
  const auto bytes = fixture("sample.jpg");
  auto policy = limits;
  policy.inputBytes = bytes.size() - 1;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::ResourceLimit);
  policy = limits;
  policy.sourcePixels = 799;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {1, 1}}).outcome, Outcome::ResourceLimit);
  policy = limits;
  policy.sourceExtent = 39;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::ResourceLimit);
  policy = limits;
  policy.decodedBytes = 3199;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::ResourceLimit);
  policy = limits;
  policy.sourcePixels = 0;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::ResourceLimit);
}
TEST(Images, UnsupportedDamagedAndClosedDeviceOutcomes) {
  EXPECT_EQ(decodeBytes("not an image").outcome, Outcome::Unsupported);
  auto bytes = fixture("sample.png");
  bytes.truncate(40);
  EXPECT_EQ(decodeBytes(bytes).outcome, Outcome::Damaged);
  QBuffer closed;
  EXPECT_EQ(decode(closed, {.limits = limits, .bound = {}}, running).outcome, Outcome::IoFailure);
}
TEST(Images, CallerDeviceSurvivesAndPathIsNeverReopened) {
  QTemporaryDir dir;
  const auto path = dir.filePath("old.jpg");
  QFile writer(path);
  ASSERT_TRUE(writer.open(QIODevice::WriteOnly));
  writer.write(fixture("sample.png"));
  writer.close();
  QFile device(path);
  ASSERT_TRUE(device.open(QIODevice::ReadOnly));
  ASSERT_TRUE(QFile::rename(path, dir.filePath("moved")));
  ASSERT_TRUE(writer.open(QIODevice::WriteOnly));
  writer.write("replaced");
  writer.close();
  auto result = decode(device, {.limits = limits, .bound = {}}, running);
  EXPECT_EQ(result.outcome, Outcome::Success);
  EXPECT_EQ(result.inspection.format, "png");
  EXPECT_TRUE(device.isOpen());
  EXPECT_TRUE(device.seek(0));
  EXPECT_EQ(device.readAll(), fixture("sample.png"));
}
TEST(Images, InitialAndLaterDeviceFailuresRemainIoFailures) {
  auto bytes = ExifFixture::jpegWithApp1(ExifFixture::sonyPayload());
  for (const auto operation : {Operation::Inspect, Operation::Decode, Operation::Metadata}) {
    SCOPED_TRACE(static_cast<int>(operation));
    ControlledBuffer baseline(&bytes);
    ASSERT_EQ(run(operation, baseline), Outcome::Success);
    ASSERT_GT(baseline.reads, 1);
    ASSERT_GT(baseline.seeks, 1);
    // Discover the successful operation's I/O boundaries rather than assuming a codec's call count.
    for (int read = 1; read <= baseline.reads; ++read) {
      SCOPED_TRACE(read);
      ControlledBuffer device(&bytes);
      device.failRead = read;
      EXPECT_EQ(run(operation, device), Outcome::IoFailure);
      EXPECT_GE(device.reads, read);
      EXPECT_TRUE(device.isOpen());
    }
    for (int seek = 1; seek <= baseline.seeks; ++seek) {
      SCOPED_TRACE(seek);
      ControlledBuffer device(&bytes);
      device.failSeek = seek;
      EXPECT_EQ(run(operation, device), Outcome::IoFailure);
      EXPECT_GE(device.seeks, seek);
      EXPECT_TRUE(device.isOpen());
    }
  }
}
TEST(Images, CancellationBeforeWorkAndAtEveryReadDiscardsOutput) {
  auto bytes = ExifFixture::jpegWithApp1(ExifFixture::sonyPayload());
  for (const auto operation : {Operation::Inspect, Operation::Decode, Operation::Metadata}) {
    SCOPED_TRACE(static_cast<int>(operation));
    ControlledBuffer baseline(&bytes);
    ASSERT_EQ(run(operation, baseline), Outcome::Success);
    for (int read = 0; read <= baseline.reads; ++read) {
      SCOPED_TRACE(read);
      ControlledBuffer device(&bytes);
      device.cancelled = read == 0;
      device.cancelRead = read;
      EXPECT_EQ(run(operation, device), Outcome::Cancelled);
      EXPECT_TRUE(device.isOpen());
      if (read == 0) {
        EXPECT_EQ(device.reads, 0);
        EXPECT_EQ(device.seeks, 0);
      } else {
        EXPECT_GE(device.reads, read);
      }
    }
  }
}
TEST(Images, MetadataContainerReadsPropagateFailuresAndCancellation) {
  using namespace ExifFixture;
  const auto payload = sonyPayload();
  const auto raw = payload.sliced(6);
  // Extend TIFF beyond a scan block to exercise later provider-controlled reads.
  const QList<QByteArray> containers{png(pngChunk("eXIf", raw)), webp(webpChunk("EXIF", raw)),
                                     raw + QByteArray(2 * 1024 * 1024, '\0')};
  for (auto bytes : containers) {
    ControlledBuffer baseline(&bytes);
    ASSERT_EQ(readMetadata(baseline, limits, running).facts, parseExif(payload));
    for (int read = 1; read <= baseline.reads; ++read) {
      SCOPED_TRACE(read);
      ControlledBuffer failed(&bytes);
      failed.failRead = read;
      EXPECT_EQ(run(Operation::Metadata, failed), Outcome::IoFailure);
      EXPECT_TRUE(failed.isOpen());
      ControlledBuffer cancelled(&bytes);
      cancelled.cancelRead = read;
      EXPECT_EQ(run(Operation::Metadata, cancelled), Outcome::Cancelled);
      EXPECT_TRUE(cancelled.isOpen());
    }
    for (int seek = 1; seek <= baseline.seeks; ++seek) {
      ControlledBuffer failed(&bytes);
      failed.failSeek = seek;
      EXPECT_EQ(run(Operation::Metadata, failed), Outcome::IoFailure);
      EXPECT_TRUE(failed.isOpen());
    }
  }
}
TEST(Images, RasterLimitsAcceptExactBoundaries) {
  auto bytes = fixture("sample.jpg");
  for (const auto field : {&Limits::inputBytes, &Limits::sourcePixels, &Limits::decodedBytes}) {
    auto policy = limits;
    policy.*field = field == &Limits::inputBytes ? bytes.size() : field == &Limits::sourcePixels ? 800 : 3200;
    QBuffer device(&bytes);
    device.open(QIODevice::ReadOnly);
    EXPECT_EQ(inspect(device, policy, running).outcome, Outcome::Success);
    EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::Success);
    --(policy.*field);
    EXPECT_EQ(inspect(device, policy, running).outcome, Outcome::ResourceLimit);
    const auto rejected = decodeBytes(bytes, {.limits = policy, .bound = {1, 1}});
    EXPECT_EQ(rejected.outcome, Outcome::ResourceLimit);
    EXPECT_TRUE(rejected.image.isNull());
  }
  auto policy = limits;
  policy.sourceExtent = 40;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::Success);
  policy.sourceExtent = 39;
  EXPECT_EQ(decodeBytes(bytes, {.limits = policy, .bound = {}}).outcome, Outcome::ResourceLimit);
  policy = limits;
  policy.inputBytes = bytes.size();
  EXPECT_EQ(metadata(bytes, policy).outcome, Outcome::Success);
  --policy.inputBytes;
  EXPECT_EQ(metadata(bytes, policy).outcome, Outcome::ResourceLimit);
}
TEST(Images, StructuredExifAndContainerExtraction) {
  using namespace ExifFixture;
  const auto expected = parseExif(sonyPayload());
  EXPECT_EQ(expected.make, "SONY");
  EXPECT_EQ(expected.model, "ILCE-7M4");
  ASSERT_TRUE(expected.exposureSeconds);
  EXPECT_DOUBLE_EQ(*expected.exposureSeconds, 0.01);
  EXPECT_EQ(expected.aperture, 8);
  EXPECT_EQ(expected.iso, 100);
  EXPECT_EQ(expected.latitude, 50.45);
  EXPECT_EQ(expected.longitude, -30.52);
  EXPECT_EQ(metadata(jpegWithApp1(sonyPayload())).facts, expected);
  EXPECT_EQ(metadata(sonyPayload().sliced(6)).facts, expected);
  const auto tiff = sonyPayload().sliced(6);
  auto png = fixture("sample.png");
  QByteArray length(4, '\0');
  qToBigEndian(quint32(tiff.size()), length.data());
  png.insert(png.size() - 12, length + "eXIf" + tiff + QByteArray(4, '\0'));
  EXPECT_EQ(metadata(png).facts, expected);
  const auto chunks = QByteArray("EXIF") + le32(tiff.size()) + tiff;
  EXPECT_EQ(metadata(QByteArray("RIFF") + le32(chunks.size() + 4) + "WEBP" + chunks).facts, expected);
  auto policy = limits;
  policy.metadataBytes = 10;
  EXPECT_EQ(metadata(png, policy).outcome, Outcome::ResourceLimit);
  EXPECT_EQ(metadata(png, policy).facts, ExifFacts{});
  policy = limits;
  policy.tiffMetadataBytes = 10;
  EXPECT_EQ(metadata(tiff, policy).outcome, Outcome::ResourceLimit);
  EXPECT_EQ(parseExif("broken"), ExifFacts{});
}
TEST(Images, CompactWebPFallbackCorruptionAndLimits) {
  const auto original = fixture("compact.webp");
  const auto result = decodeBytes(original);
  ASSERT_EQ(result.outcome, Outcome::Success);
  EXPECT_EQ(result.image.pixelColor(0, 0), QColor(255, 0, 0, 128));
  for (qsizetype n = 0; n < original.size(); ++n) EXPECT_TRUE(decodeBytes(original.first(n)).image.isNull()) << n;
  auto broken = original;
  broken[20] = 0;
  EXPECT_TRUE(decodeBytes(broken).image.isNull());
  broken = original;
  broken.replace(21, 4, QByteArray::fromHex("ffffff1f"));
  EXPECT_EQ(decodeBytes(broken).outcome, Outcome::ResourceLimit);
  for (const auto* name : {"extended.webp", "animated.webp", "lossy.webp"}) {
    auto bytes = fixture(name);
    QBuffer device(&bytes);
    device.open(QIODevice::ReadOnly);
    QImageReader reader(&device);
    auto expected = reader.read();
    EXPECT_EQ(decodeBytes(bytes).image.convertToFormat(QImage::Format_RGBA8888),
              expected.convertToFormat(QImage::Format_RGBA8888));
  }
}
TEST(Images, CompactWebPInspectionMatchesDecode) {
  auto bytes = fixture("compact.webp");
  QBuffer device(&bytes);
  device.open(QIODevice::ReadOnly);
  auto info = inspect(device, limits, running);
  EXPECT_EQ(info.outcome, Outcome::Success);
  EXPECT_EQ(info.format, "webp");
  EXPECT_EQ(info.sourceSize, QSize(1, 1));
}
TEST(Images, MetadataBlockAndTiffScanLimitsAcceptExactBoundaries) {
  using namespace ExifFixture;
  const auto payload = sonyPayload();
  const auto raw = payload.sliced(6);
  const auto expected = parseExif(payload);
  const QList<QPair<QByteArray, qint64>> containers{{jpegWithApp1(payload), payload.size()},
                                                    {png(pngChunk("eXIf", raw)), raw.size()},
                                                    {webp(webpChunk("EXIF", raw)), raw.size()},
                                                    {webp(webpChunk("EXIF", payload)), payload.size()}};
  for (const auto& [bytes, size] : containers) {
    auto policy = limits;
    policy.metadataBytes = size;
    EXPECT_EQ(metadata(bytes, policy).outcome, Outcome::Success);
    EXPECT_EQ(metadata(bytes, policy).facts, expected);
    --policy.metadataBytes;
    const auto rejected = metadata(bytes, policy);
    EXPECT_EQ(rejected.outcome, Outcome::ResourceLimit);
    EXPECT_EQ(rejected.facts, ExifFacts{});
  }
  auto policy = limits;
  policy.tiffMetadataBytes = raw.size();
  EXPECT_EQ(metadata(raw, policy).outcome, Outcome::Success);
  EXPECT_EQ(metadata(raw, policy).facts, expected);
  --policy.tiffMetadataBytes;
  EXPECT_EQ(metadata(raw, policy).outcome, Outcome::ResourceLimit);
  EXPECT_EQ(metadata(raw, policy).facts, ExifFacts{});
}
TEST(Images, MetadataRecordBudgetsStopBeforeTheNextRecord) {
  using namespace ExifFixture;
  const auto payload = sonyPayload();
  const auto raw = payload.sliced(6);
  const QList<QByteArray> containers{
      QByteArray("\xff\xd8", 2) + jpegSegment(0xfe, "skip") + jpegSegment(0xfe, "skip") + jpegSegment(0xe1, payload),
      png(pngChunk("tEXt", "skip") + pngChunk("tEXt", "skip") + pngChunk("eXIf", raw)),
      webp(webpChunk("JUNK", "odd") + webpChunk("JUNK", "odd") + webpChunk("EXIF", raw))};
  for (auto bytes : containers) {
    auto policy = limits;
    policy.metadataRecords = 3;
    EXPECT_EQ(metadata(bytes, policy).facts, parseExif(payload));
    policy.metadataRecords = 2;
    ControlledBuffer device(&bytes);
    const auto result = readMetadata(device, policy, running);
    EXPECT_EQ(result.outcome, Outcome::Success);
    EXPECT_EQ(result.facts, ExifFacts{});
    // At most a 12-byte signature and two 8-byte chunk headers; skipped bodies are not read.
    EXPECT_LE(device.bytesRead, 12 + 2 * 8);
    EXPECT_TRUE(device.isOpen());
  }
  auto bytes = png(QByteArray{});
  for (int n = 0; n < 5000; ++n) bytes += pngChunk("tEXt", {});
  ControlledBuffer device(&bytes);
  EXPECT_EQ(readMetadata(device, limits, running).facts, ExifFacts{});
  EXPECT_LE(device.bytesRead, 8 + 4096 * 8);
}
TEST(Images, TruncatedMetadataSegmentsAndChunksAreBestEffort) {
  using namespace ExifFixture;
  const auto payload = sonyPayload();
  const auto raw = payload.sliced(6);
  const QList<QPair<QByteArray, qsizetype>> containers{{QByteArray("\xff\xd8", 2) + jpegSegment(0xe1, payload), 0},
                                                       {png(pngChunk("eXIf", raw)), 4},
                                                       {webp(webpChunk("EXIF", raw)), raw.size() & 1}};
  for (const auto& [bytes, trailer] : containers) {
    for (qsizetype size = 0; size < bytes.size() - trailer; ++size) {
      SCOPED_TRACE(size);
      const auto result = metadata(bytes.first(size));
      EXPECT_EQ(result.outcome, Outcome::Success);
      EXPECT_EQ(result.facts, ExifFacts{});
    }
  }
  // Invalid JPEG length, a skipped PNG chunk beyond EOF and an incomplete WebP padded chunk.
  for (const auto& bytes : {QByteArray::fromHex("ffd8ffe10001"), png(QByteArray::fromHex("ffffffff") + "tEXt"),
                            webp(QByteArray("JUNK") + le32(3) + "ab")}) {
    EXPECT_EQ(metadata(bytes).facts, ExifFacts{});
  }
}
TEST(Images, WebPOddChunkPaddingKeepsFollowingExifAligned) {
  using namespace ExifFixture;
  const auto payload = sonyPayload();
  const auto junk = webpChunk("JUNK", "odd");
  const auto exif = webpChunk("EXIF", payload.sliced(6));
  EXPECT_EQ(metadata(webp(junk + exif)).facts, parseExif(payload));
  EXPECT_EQ(metadata(webp(junk.first(junk.size() - 1) + exif)).facts, ExifFacts{});
}
TEST(Images, MalformedTiffOffsetsAndInvalidExifValuesAreIgnored) {
  using namespace ExifFixture;
  auto raw = tiff({text(0x010f, "Camera")}, {}, {});
  raw.replace(4, 4, le32(0xfffffff0));
  EXPECT_EQ(metadata(raw).facts, ExifFacts{});
  raw = tiff({text(0x010f, "Camera")}, {}, {});
  raw.replace(18, 4, le32(0xfffffff0));  // Out-of-line Make value lies beyond the payload.
  EXPECT_TRUE(metadata(raw).facts.make.isEmpty());
  raw = tiff({text(0x010f, "Camera")}, {}, {});
  raw.replace(8 + 2 + 3 * 12, 4, le32(8));  // Cyclic next-IFD pointer must terminate.
  EXPECT_EQ(metadata(raw).facts.make, "Camera");
  const auto invalid =
      QByteArray("Exif\0\0", 6) + tiff({shortValue(0x010f, 42), text(0x0110, "Still valid")},
                                       {rationals(0x829a, {{1, 0}}), text(0x829d, "invalid"), text(0x8827, "invalid")},
                                       {text(0x0001, "N"), rationals(0x0002, {{91, 1}, {0, 1}, {0, 1}}),
                                        text(0x0003, "W"), rationals(0x0004, {{30, 1}, {0, 1}, {0, 1}})});
  const auto facts = parseExif(invalid);
  EXPECT_TRUE(facts.make.isEmpty());
  EXPECT_EQ(facts.model, "Still valid");
  EXPECT_FALSE(facts.exposureSeconds);
  EXPECT_FALSE(facts.aperture);
  EXPECT_FALSE(facts.iso);
  EXPECT_FALSE(facts.latitude);
  EXPECT_FALSE(facts.longitude);
  const auto invalidReference =
      QByteArray("Exif\0\0", 6) + tiff({}, {},
                                       {text(0x0001, "X"), rationals(0x0002, {{50, 1}, {0, 1}, {0, 1}}),
                                        text(0x0003, "W"), rationals(0x0004, {{30, 1}, {0, 1}, {0, 1}})});
  EXPECT_FALSE(parseExif(invalidReference).latitude);
  EXPECT_FALSE(parseExif(invalidReference).longitude);
}
TEST(Images, OversizedMetadataDoesNotInvalidateRasterInspectionOrDecode) {
  using namespace ExifFixture;
  auto bytes = jpegWithApp1(sonyPayload());
  auto policy = limits;
  policy.metadataBytes = sonyPayload().size() - 1;
  QBuffer device(&bytes);
  device.open(QIODevice::ReadOnly);
  const auto info = inspect(device, policy, running);
  EXPECT_EQ(info.outcome, Outcome::Success);
  EXPECT_EQ(info.sourceSize, QSize(4, 3));
  EXPECT_EQ(info.metadata.outcome, Outcome::ResourceLimit);
  EXPECT_EQ(info.metadata.facts, ExifFacts{});
  const auto result = decode(device, {.limits = policy, .bound = {}}, running);
  EXPECT_EQ(result.outcome, Outcome::Success);
  EXPECT_EQ(result.image.size(), QSize(4, 3));
  EXPECT_TRUE(device.isOpen());
}
TEST(Images, DiscoveryAliases) {
  EXPECT_EQ(canonicalFormat("JPG"), "jpeg");
  EXPECT_EQ(canonicalFormat("tif"), "tiff");
  const auto formats = supportedSuffixes();
  EXPECT_TRUE(formats.contains("png"));
  EXPECT_TRUE(formats.contains("jpeg"));
  EXPECT_TRUE(formats.contains("jpg"));
}
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  QImageReader::setAllocationLimit(128);
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
