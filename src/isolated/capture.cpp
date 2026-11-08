// SPDX-License-Identifier: GPL-3.0-or-later
#include "capture.h"

#include <algorithm>
#include <array>
#include <utility>

namespace HolonightImages::Isolation {
CaptureResult capture(QIODevice& device, qint64 limit, const std::atomic_bool& cancelled) {
  if (cancelled.load()) {
    return {.outcome = CaptureOutcome::Cancelled, .bytes = {}};
  }
  if (limit <= 0 || limit > inputCeiling) {
    return {.outcome = CaptureOutcome::ResourceLimit, .bytes = {}};
  }
  if (!device.isOpen() || !device.isReadable() || device.isSequential()) {
    return {.outcome = CaptureOutcome::IoFailure, .bytes = {}};
  }
  if (cancelled.load()) {
    return {.outcome = CaptureOutcome::Cancelled, .bytes = {}};
  }
  const bool sought = device.seek(0);
  if (cancelled.load()) {
    return {.outcome = CaptureOutcome::Cancelled, .bytes = {}};
  }
  if (!sought) {
    return {.outcome = CaptureOutcome::IoFailure, .bytes = {}};
  }
  QByteArray bytes;
  std::array<char, 65536> block{};
  for (;;) {
    if (cancelled.load()) {
      return {.outcome = CaptureOutcome::Cancelled, .bytes = {}};
    }
    const auto remaining = limit - bytes.size();
    const auto count = device.read(block.data(), (remaining != 0) ? std::min<qint64>(remaining, block.size()) : 1);
    if (cancelled.load()) {
      return {.outcome = CaptureOutcome::Cancelled, .bytes = {}};
    }
    if (count < 0) {
      return {.outcome = CaptureOutcome::IoFailure, .bytes = {}};
    }
    if (count == 0) {
      if (cancelled.load()) {
        return {.outcome = CaptureOutcome::Cancelled, .bytes = {}};
      }
      return {.outcome = CaptureOutcome::Success, .bytes = std::move(bytes)};
    }
    if (remaining == 0) {
      return {.outcome = CaptureOutcome::ResourceLimit, .bytes = {}};
    }
    bytes.append(block.data(), count);
  }
}
}  // namespace HolonightImages::Isolation
