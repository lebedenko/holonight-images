#pragma once

#include <QBuffer>
#include <QCoreApplication>
#include <QImageReader>

#include <cstdint>
#include <cstdlib>
#include <holonight_images/image.h>

namespace Fuzz {
inline void require(bool condition) {
  if (!condition) std::abort();
}
inline void initialize() {
  static int argc = 1;
  static char name[] = "images-fuzz";
  static char* argv[] = {name, nullptr};
  static QCoreApplication application(argc, argv);
  QImageReader::setAllocationLimit(16);
}
// Mutate bytes directly: no control header hides image signatures from the mutator.
// The same input is also exercised with deterministic read/seek/cancellation faults.
class Buffer final : public QBuffer {
 public:
  Buffer(QByteArray* bytes, int mode) : QBuffer(bytes), mode_(mode) { open(ReadOnly | Unbuffered); }
  std::atomic_bool cancelled{false};
  bool seek(qint64 offset) override {
    ++seeks_;
    return (mode_ != 2 || seeks_ < 2) && QBuffer::seek(offset);
  }

 protected:
  qint64 readData(char* data, qint64 length) override {
    ++reads_;
    if (mode_ == 1 && reads_ >= 2) return -1;
    const auto count = QBuffer::readData(data, length);
    if (mode_ == 3) cancelled.store(true);
    return count;
  }

 private:
  int mode_;
  int reads_ = 0;
  int seeks_ = 0;
};
inline HolonightImages::Limits limits(bool constrained) {
  return {.inputBytes = constrained ? 64 : 1024 * 1024,
          .sourcePixels = constrained ? 16 : 1024 * 1024,
          .sourceExtent = constrained ? 8 : 2048,
          .decodedBytes = constrained ? 64 : 4 * 1024 * 1024,
          .metadataBytes = constrained ? 32 : 64 * 1024,
          .tiffMetadataBytes = constrained ? 32 : 64 * 1024,
          .metadataRecords = constrained ? 2 : 128};
}
}  // namespace Fuzz
