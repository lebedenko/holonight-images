#include "common.h"

// Required libFuzzer entrypoint name.
// NOLINTNEXTLINE(readability-identifier-naming)
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  if (size > 1024 * 1024) {
    return 0;
  }
  Fuzz::initialize();
  QByteArray bytes(static_cast<const char*>(static_cast<const void*>(data)), static_cast<qsizetype>(size));
  for (int mode = 0; mode < 5; ++mode) {
    Fuzz::Buffer device(&bytes, mode);
    device.cancelled = mode == 4;
    HolonightImages::readMetadata(device, Fuzz::limits(mode == 4), device.cancelled);
    Fuzz::require(device.isOpen() && device.openMode() == (QIODevice::ReadOnly | QIODevice::Unbuffered));
  }
  // Constrained limits independently of cancellation.
  Fuzz::Buffer device(&bytes, 0);
  HolonightImages::readMetadata(device, Fuzz::limits(true), device.cancelled);
  Fuzz::require(device.isOpen());
  return 0;
}
