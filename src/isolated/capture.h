// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QByteArray>
#include <QIODevice>

#include <atomic>

namespace HolonightImages::Isolation {
constexpr qint64 inputCeiling = 256LL * 1024 * 1024;
enum class CaptureOutcome : unsigned char { Success, IoFailure, ResourceLimit, Cancelled };
struct CaptureResult {
  CaptureOutcome outcome;
  QByteArray bytes;
};
// Caller retains ownership and open state. Final position is unspecified.
// Synchronous, seekable input only: zero-byte reads mean EOF. Captures observed
// bytes, including concurrent changes, rather than an atomic filesystem snapshot.
CaptureResult capture(QIODevice& device, qint64 limit, const std::atomic_bool& cancelled);
}  // namespace HolonightImages::Isolation
