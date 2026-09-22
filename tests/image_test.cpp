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
TEST(Images, CancellationBeforeAndDuringReadDiscardsResults) {
  auto bytes = fixture("sample.jpg");
  std::atomic_bool cancelled{true};
  QBuffer buffer(&bytes);
  buffer.open(QIODevice::ReadOnly);
  EXPECT_EQ(decode(buffer, {.limits = limits, .bound = {}}, cancelled).outcome, Outcome::Cancelled);
  EXPECT_EQ(readMetadata(buffer, limits, cancelled).outcome, Outcome::Cancelled);
  class CancellingBuffer : public QBuffer {
   public:
    CancellingBuffer(QByteArray* data, std::atomic_bool& stop) : QBuffer(data), stop_(stop) {}

   protected:
    qint64 readData(char* data, qint64 size) override {
      auto n = QBuffer::readData(data, size);
      stop_.store(true);
      return n;
    }

   private:
    std::atomic_bool& stop_;
  } device(&bytes, cancelled);
  device.open(QIODevice::ReadOnly);
  cancelled = false;
  auto result = decode(device, {.limits = limits, .bound = {}}, cancelled);
  EXPECT_EQ(result.outcome, Outcome::Cancelled);
  EXPECT_TRUE(result.image.isNull());
}
TEST(Images, ReadFailuresHaveIoOutcome) {
  class FailedDevice : public QIODevice {
   public:
    FailedDevice() { open(ReadOnly | Unbuffered); }
    qint64 size() const override { return 100; }

   protected:
    qint64 readData(char*, qint64) override { return -1; }
    qint64 writeData(const char*, qint64) override { return -1; }
  } device;
  EXPECT_EQ(decode(device, {.limits = limits, .bound = {}}, running).outcome, Outcome::IoFailure);
  EXPECT_EQ(readMetadata(device, limits, running).outcome, Outcome::IoFailure);
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
TEST(Images, MetadataRecordBudgetDoesNotReadPastTheBudget) {
  QByteArray bytes("\x89PNG\r\n\x1a\n", 8);
  for (int n = 0; n < 5000; ++n) bytes += QByteArray("\0\0\0\0tEXt\0\0\0\0", 12);
  class Counted : public QBuffer {
   public:
    using QBuffer::QBuffer;
    qint64 count = 0;

   protected:
    qint64 readData(char* data, qint64 size) override {
      auto n = QBuffer::readData(data, size);
      if (n > 0) count += n;
      return n;
    }
  } device(&bytes);
  device.open(QIODevice::ReadOnly | QIODevice::Unbuffered);
  auto result = readMetadata(device, limits, running);
  EXPECT_EQ(result.facts, ExifFacts{});
  EXPECT_LE(device.count, 8 + 4096 * 8);
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
