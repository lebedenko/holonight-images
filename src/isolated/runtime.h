// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "protocol.h"
namespace HolonightImages::Isolation {
struct TransportResult {
  RuntimeStatus status = RuntimeStatus::Unavailable;
  std::optional<Reply> reply;
  QString diagnostic;
  qint64 elapsed = 0;
  qint64 peak_memory = 0;
  qint64 startup = 0;
  qint64 operation = 0;
};
using TransactionExchange = std::function<Reply(const Request&, const QByteArray&, bool)>;
using TransactionCoordinator = std::function<DecodeResult(const Inspection&, const TransactionExchange&)>;
TransportResult dispatch(const QString& runtime, const Request& request, const QByteArray& input,
                         const std::atomic_bool& cancelled, const TransactionCoordinator& coordinate = {});
}  // namespace HolonightImages::Isolation
