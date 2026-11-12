// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <functional>
#include <holonight_images/image.h>
#include <memory>

namespace HolonightImages {
// Infrastructure failures never manufacture a provider outcome. A result exists
// only after a complete validated reply and verified hierarchical cleanup.
enum class RuntimeStatus : unsigned char { Success, Unavailable, ProtocolFailure, Timeout, CleanupFailure, Cancelled };
// Public result fields follow the existing provider API naming.
// NOLINTBEGIN(readability-identifier-naming)
template <typename T>
struct IsolatedResult {
  RuntimeStatus runtime = RuntimeStatus::Unavailable;
  std::optional<T> result;
  QString diagnostic;
  qint64 elapsedMilliseconds = 0;
  // Observed scope peak; excludes parent capture, verification and output memory.
  qint64 peakMemoryBytes = 0;
  qint64 startupMilliseconds = 0;
  qint64 operationMilliseconds = 0;
};
// NOLINTEND(readability-identifier-naming)
// A validated, protected generation. Copies share the directory flock; the last
// copy releases it. Mutable development directories cannot produce a lease.
class GenerationLease {
 public:
  GenerationLease() = default;
  explicit operator bool() const noexcept { return static_cast<bool>(state_); }
  [[nodiscard]] QString runtimeDirectory() const;
  [[nodiscard]] bool supportsSessions() const;

 private:
  struct State;
  std::shared_ptr<State> state_;
  friend class RuntimeOwner;
  friend struct GenerationAccess;
};
// Synchronous selection epochs. Construction selects once; refresh first revokes
// acquisitions, then validates the new selection. Failure has no stale fallback.
// acquire and refresh may run concurrently. Active leases survive refresh.
class RuntimeOwner {
 public:
  explicit RuntimeOwner(QString managedDirectory);
  ~RuntimeOwner();
  RuntimeOwner(const RuntimeOwner&) = delete;
  RuntimeOwner& operator=(const RuntimeOwner&) = delete;
  RuntimeOwner(RuntimeOwner&&) = delete;
  RuntimeOwner& operator=(RuntimeOwner&&) = delete;
  [[nodiscard]] GenerationLease acquire() const;
  bool refresh();
  [[nodiscard]] bool launchesDisabled() const;
  [[nodiscard]] QString diagnostic() const;

 private:
  struct State;
  std::unique_ptr<State> state_;
};
// Available only during the coordination callback. Results are provisional: do
// not publish pixels or commit caches until sourceTransaction returns Success.
class SourceTransaction {
 public:
  ~SourceTransaction() = default;
  SourceTransaction(SourceTransaction&&) = delete;
  SourceTransaction& operator=(SourceTransaction&&) = delete;
  SourceTransaction(const SourceTransaction&) = delete;
  SourceTransaction& operator=(const SourceTransaction&) = delete;
  DecodeResult decodeCachedPng(QIODevice& candidate, const DecodeOptions& options);
  DecodeResult decodeSource(const DecodeOptions& options);

 private:
  friend class IsolatedClient;
  friend struct TransactionAccess;
  using Exchange = std::function<DecodeResult(QIODevice*, const DecodeOptions&)>;
  explicit SourceTransaction(Exchange exchange) : exchange_(std::move(exchange)) {}
  Exchange exchange_;
};
using SourceCoordinator = std::function<DecodeResult(const Inspection&, SourceTransaction&)>;
// Session success (operator bool) proves validated replies and transaction-state destruction
// acknowledged by a living helper. It does not prove terminal cleanup. A worker
// compromise can persist across successful transactions until retirement.
// NOLINTBEGIN(readability-identifier-naming)
template <typename T>
struct SessionResult {
  // Infrastructure status alone does not claim that a command was dispatched.
  // Local source/limit rejection preserves the ready worker without an acknowledgement.
  bool completionAcknowledged = false;
  explicit operator bool() const noexcept {
    return runtime == RuntimeStatus::Success && completionAcknowledged && result.has_value();
  }
  RuntimeStatus runtime = RuntimeStatus::Unavailable;
  std::optional<T> result;
  QString diagnostic;
  qint64 elapsedMilliseconds = 0;
  qint64 peakMemoryBytes = 0;
  qint64 operationMilliseconds = 0;
};
struct SessionLifecycleResult {
  RuntimeStatus runtime = RuntimeStatus::Unavailable;
  QString diagnostic;
  qint64 startupMilliseconds = 0;
};
// NOLINTEND(readability-identifier-naming)
// Caller-owned synchronous mechanism; all calls and destruction must occur on
// the thread that prepared it. No scheduling, cache or recycling policy lives here.
// Requires a protected generation lease. Preparation and each active transaction
// have separate 15-second deadlines; retirement has a five-second cleanup budget.
// Capture retains the blocking-read limitation documented for IsolatedClient.
class ReusableSession {
 public:
  explicit ReusableSession(GenerationLease generation);
  ~ReusableSession();
  ReusableSession(ReusableSession&&) noexcept;
  ReusableSession& operator=(ReusableSession&&) noexcept;
  ReusableSession(const ReusableSession&) = delete;
  ReusableSession& operator=(const ReusableSession&) = delete;
  // Called on this session's thread after the first command enters the wire.
  // Exceptions poison and retire the session, like coordination exceptions.
  void setTransactionStartedCallback(std::function<void()> callback);
  SessionLifecycleResult prepare(const std::atomic_bool& cancelled);
  SessionResult<DecodeResult> sourceTransaction(QIODevice& source, const Limits& limits,
                                                const std::atomic_bool& cancelled, const SourceCoordinator& coordinate);
  SessionLifecycleResult retire();
  [[nodiscard]] bool ready() const;
  // memory.current, or -1 when observation fails. No retained idle worker may be
  // counted as having zero memory solely because observation failed.
  [[nodiscard]] qint64 idleMemoryBytes() const;

 private:
  class State;
  std::unique_ptr<State> state_;
};
// Linux, caller-owned synchronous client. No source paths, scheduling or caches.
// Each operation creates a fresh helper. Exclusive access to source is required.
// Capture starts at zero, preserves ownership/open state, ignores size(), and
// leaves position unspecified. Cancellation cannot interrupt a blocking read.
// Capture and complete runtime verification precede the 15-second request deadline
// after launcher startup. Cleanup has a separate five-second budget. Cancellation
// checks cannot interrupt runtime hashing either; there is no whole-call deadline.
// Caller output budgets, Qt's 256 MiB allocation limit and the 2 GiB/no-swap scope
// limit are separate controls; none bounds total parent RSS.
// Named color spaces (including matching Adobe RGB) and untagged pixels are supported;
// other valid profiles return Unsupported without conversion or profile dropping.
// Requires Linux namespaces, bubblewrap, a user systemd manager and cgroup v2.
// The trusted gate loads host dependencies before entering the verified sandbox.
// Explicit bundle selection is required; no environment or host-codec fallback.
class IsolatedClient {
 public:
  explicit IsolatedClient(QString runtimeDirectory);
  explicit IsolatedClient(GenerationLease generation);
  IsolatedResult<Inspection> inspect(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled,
                                     OrientationPolicy orientation = OrientationPolicy::Apply,
                                     bool metadata = true) const;
  IsolatedResult<MetadataResult> readMetadata(QIODevice& source, const Limits& limits,
                                              const std::atomic_bool& cancelled) const;
  IsolatedResult<DecodeResult> decode(QIODevice& source, const DecodeOptions& options,
                                      const std::atomic_bool& cancelled) const;

  // One inspection, at most four cached PNG attempts, then at most one source
  // decode. Callback exceptions terminate the transaction. No helper survives
  // the call; only the selected result after verified cleanup is returned.
  IsolatedResult<DecodeResult> sourceTransaction(QIODevice& source, const Limits& limits,
                                                 const std::atomic_bool& cancelled,
                                                 const SourceCoordinator& coordinate) const;

 private:
  QString runtimeDirectory_;
  GenerationLease generation_;
};
}  // namespace HolonightImages
