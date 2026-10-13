#include "common.h"

// Required libFuzzer entrypoint name.
// NOLINTNEXTLINE(readability-identifier-naming)
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  if (size > 1024 * 1024) {
    return 0;
  }
  Fuzz::initialize();
  HolonightImages::parseExif(
      QByteArray(static_cast<const char*>(static_cast<const void*>(data)), static_cast<qsizetype>(size)));
  return 0;
}
