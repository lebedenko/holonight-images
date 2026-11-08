// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "protocol.h"
namespace HolonightImages::Isolation {
void verifyRuntime(const QString& directory);
struct TransportResult {
  RuntimeStatus status = RuntimeStatus::Unavailable;
  std::optional<Reply> reply;
  QString diagnostic;
  qint64 elapsed = 0;
  qint64 peak_memory = 0;
  qint64 startup = 0;
  qint64 operation = 0;
};
TransportResult dispatch(const QString& runtime, const Request& request, const QByteArray& input,
                         const std::atomic_bool& cancelled);
}  // namespace HolonightImages::Isolation
