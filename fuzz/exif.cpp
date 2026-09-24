#include "common.h"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  if (size > 1024 * 1024) return 0;
  Fuzz::initialize();
  HolonightImages::parseExif(QByteArray(reinterpret_cast<const char*>(data), static_cast<qsizetype>(size)));
  return 0;
}
