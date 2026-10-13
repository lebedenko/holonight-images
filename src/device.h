#pragma once
#include <QIODevice>

#include <holonight_images/image.h>
namespace HolonightImages {
// A device-only view prevents codecs from recovering/reopening a QFile pathname.
// Record read failures even when a plugin reports them as invalid image data.
class Device final : public QIODevice {
 public:
  explicit Device(QIODevice& source) : source_(source) { open(ReadOnly | Unbuffered); }
  [[nodiscard]] bool failed() const { return failed_; }
  [[nodiscard]] qint64 size() const override { return source_.size(); }
  [[nodiscard]] bool isSequential() const override { return false; }
  bool seek(qint64 offset) override {
    if (!source_.seek(offset)) {
      failed_ = true;
      return false;
    }
    return QIODevice::seek(offset);
  }

 protected:
  qint64 readData(char* data, qint64 size) override {
    const auto count = source_.read(data, size);
    if (count < 0) {
      failed_ = true;
    }
    return count;
  }
  qint64 writeData(const char* /*data*/, qint64 /*len*/) override { return -1; }

 private:
  QIODevice& source_;
  bool failed_ = false;
};
inline bool valid(const Limits& limits) {
  return limits.inputBytes > 0 && limits.sourcePixels > 0 && limits.sourceExtent > 0 && limits.decodedBytes > 0 &&
         limits.metadataBytes > 0 && limits.tiffMetadataBytes > 0 && limits.metadataRecords > 0;
}
}  // namespace HolonightImages
