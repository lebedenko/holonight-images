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
// Synchronous transport; construct/use/retire on one thread. One-shot and reusable
// execution share launch, exchange validation and exactly-once retirement.
class Execution {
 public:
  explicit Execution(QString runtime, GenerationLease lease = {});
  ~Execution();
  Execution(Execution&& other) noexcept;
  Execution& operator=(Execution&& other) noexcept;
  Execution(const Execution&) = delete;
  Execution& operator=(const Execution&) = delete;
  void setTransactionStartedCallback(std::function<void()> callback);
  TransportResult prepare(const std::atomic_bool& cancelled, bool reusable);
  TransportResult transaction(const Request& request, const QByteArray& input, const std::atomic_bool& cancelled,
                              const TransactionCoordinator& coordinate = {});
  TransportResult retire();
  [[nodiscard]] bool ready() const;
  [[nodiscard]] qint64 idleMemory() const;

 private:
  void dispose();
  class State;
  std::unique_ptr<State> state_;
};
TransportResult dispatch(const QString& runtime, const Request& request, const QByteArray& input,
                         const std::atomic_bool& cancelled, const TransactionCoordinator& coordinate = {},
                         const GenerationLease& generation = {});
}  // namespace HolonightImages::Isolation
