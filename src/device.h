#pragma once
#include <QIODevice>

#include <holonight_images/image.h>
namespace HolonightImages {
// A device-only view prevents codecs from recovering/reopening a QFile pathname.
// Record read failures even when a plugin reports them as invalid image data.
class Device final : public QIODevice {
 public:
  explicit Device(QIODevice& source) : source_(source) { open(ReadOnly | Unbuffered); }
  bool failed = false;
  qint64 size() const override { return source_.size(); }
  bool isSequential() const override { return false; }
  bool seek(qint64 offset) override {
    if (!source_.seek(offset)) {
      failed = true;
      return false;
    }
    return QIODevice::seek(offset);
  }

 protected:
  qint64 readData(char* data, qint64 size) override {
    const auto count = source_.read(data, size);
    if (count < 0) failed = true;
    return count;
  }
  qint64 writeData(const char*, qint64) override { return -1; }

 private:
  QIODevice& source_;
};
inline bool valid(const Limits& l) {
  return l.inputBytes > 0 && l.sourcePixels > 0 && l.sourceExtent > 0 && l.decodedBytes > 0 && l.metadataBytes > 0 &&
         l.tiffMetadataBytes > 0 && l.metadataRecords > 0;
}
}  // namespace HolonightImages
