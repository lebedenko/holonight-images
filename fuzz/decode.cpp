#include "common.h"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
  if (size > 1024 * 1024) return 0;
  Fuzz::initialize();
  QByteArray bytes(reinterpret_cast<const char*>(data), static_cast<qsizetype>(size));
  for (int mode = 0; mode < 6; ++mode) {
    const auto limits = Fuzz::limits(mode == 5);
    const auto orientation =
        mode % 2 == 0 ? HolonightImages::OrientationPolicy::Apply : HolonightImages::OrientationPolicy::Ignore;
    Fuzz::Buffer source(&bytes, mode);
    source.cancelled = mode == 4;
    HolonightImages::inspect(source, limits, source.cancelled, orientation);
    Fuzz::require(source.isOpen());
    Fuzz::Buffer device(&bytes, mode);
    device.cancelled = mode == 4;
    const QSize bound(63, 47);
    const auto result = HolonightImages::decode(device, {.limits = limits, .bound = bound, .orientation = orientation},
                                                device.cancelled);
    Fuzz::require(device.isOpen() && device.openMode() == (QIODevice::ReadOnly | QIODevice::Unbuffered));
    if (result.outcome != HolonightImages::Outcome::Success) {
      Fuzz::require(result.image.isNull());
    } else {
      Fuzz::require(!result.image.isNull() && result.image.width() <= bound.width() &&
                    result.image.height() <= bound.height() && result.image.sizeInBytes() <= limits.decodedBytes);
    }
  }
  return 0;
}
