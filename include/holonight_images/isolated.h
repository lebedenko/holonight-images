// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <holonight_images/image.h>

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
  IsolatedResult<Inspection> inspect(QIODevice& source, const Limits& limits, const std::atomic_bool& cancelled,
                                     OrientationPolicy orientation = OrientationPolicy::Apply,
                                     bool metadata = true) const;
  IsolatedResult<MetadataResult> readMetadata(QIODevice& source, const Limits& limits,
                                              const std::atomic_bool& cancelled) const;
  IsolatedResult<DecodeResult> decode(QIODevice& source, const DecodeOptions& options,
                                      const std::atomic_bool& cancelled) const;

 private:
  QString runtimeDirectory_;
};
}  // namespace HolonightImages
