// SPDX-License-Identifier: GPL-3.0-or-later
#include "source-capture.h"

#include <algorithm>
#include <array>
#include <utility>

namespace Comparison {
CaptureResult capture(QIODevice& device, qint64 limit, const std::atomic_bool& cancelled) {
  if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
  if (limit <= 0 || limit > inputCeiling) return {CaptureOutcome::ResourceLimit, {}};
  if (!device.isOpen() || !device.isReadable() || device.isSequential()) return {CaptureOutcome::IoFailure, {}};
  if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
  const bool sought = device.seek(0);
  if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
  if (!sought) return {CaptureOutcome::IoFailure, {}};
  QByteArray bytes;
  std::array<char, 65536> block;
  for (;;) {
    if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
    const auto remaining = limit - bytes.size();
    const auto count = device.read(block.data(), remaining ? std::min<qint64>(remaining, block.size()) : 1);
    if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
    if (count < 0) return {CaptureOutcome::IoFailure, {}};
    if (count == 0) {
      if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
      return {CaptureOutcome::Success, std::move(bytes)};
    }
    if (!remaining) return {CaptureOutcome::ResourceLimit, {}};
    bytes.append(block.data(), count);
  }
}
}  // namespace Comparison
