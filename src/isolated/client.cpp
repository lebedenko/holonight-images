// SPDX-License-Identifier: GPL-3.0-or-later
#include "../device.h"
#include "capture.h"
#include "runtime.h"

#include <QElapsedTimer>

namespace HolonightImages {
namespace {
template <typename T, typename Select>
IsolatedResult<T> run(const QString& runtime, QIODevice& source, const Isolation::Request& request,
                      const std::atomic_bool& cancelled, Select select) {
  QElapsedTimer clock;
  clock.start();
  IsolatedResult<T> result;
  const auto& limits = request.options.limits;
  auto local = [&](Outcome outcome) {
    T value;
    value.outcome = outcome;
    result.runtime = RuntimeStatus::Success;
    result.result = std::move(value);
    result.elapsedMilliseconds = clock.elapsed();
    return result;
  };
  if (cancelled.load()) {
    result.runtime = RuntimeStatus::Cancelled;
    return result;
  }
  if (!valid(limits) || limits.inputBytes > Isolation::byteCeiling || limits.decodedBytes > Isolation::byteCeiling ||
      limits.metadataBytes > Isolation::byteCeiling || limits.tiffMetadataBytes > Isolation::byteCeiling ||
      limits.sourcePixels > INT_MAX) {
    return local(Outcome::ResourceLimit);
  }
  if (request.options.orientation != OrientationPolicy::Apply &&
      request.options.orientation != OrientationPolicy::Ignore) {
    return local(Outcome::Unsupported);
  }
  auto captured = Isolation::capture(source, limits.inputBytes, cancelled);
  if (captured.outcome == Isolation::CaptureOutcome::Cancelled) {
    result.runtime = RuntimeStatus::Cancelled;
    return result;
  }
  if (captured.outcome == Isolation::CaptureOutcome::IoFailure) {
    return local(Outcome::IoFailure);
  }
  if (captured.outcome == Isolation::CaptureOutcome::ResourceLimit) {
    return local(Outcome::ResourceLimit);
  }
  auto wireRequest = request;
  if (wireRequest.options.bound.isEmpty()) {
    wireRequest.options.bound = {};
  }
  auto transport = Isolation::dispatch(runtime, wireRequest, captured.bytes, cancelled);
  result.runtime = transport.status;
  result.diagnostic = transport.diagnostic;
  result.elapsedMilliseconds = clock.elapsed();
  result.peakMemoryBytes = transport.peak_memory;
  result.startupMilliseconds = transport.startup;
  result.operationMilliseconds = transport.operation;
  if (transport.reply) {
    result.result = select(std::move(*transport.reply));
  }
  return result;
}
}  // namespace
IsolatedClient::IsolatedClient(QString runtimeDirectory) : runtimeDirectory_(std::move(runtimeDirectory)) {}
IsolatedResult<Inspection> IsolatedClient::inspect(QIODevice& source, const Limits& limits,
                                                   const std::atomic_bool& cancelled, OrientationPolicy orientation,
                                                   bool metadata) const {
  return run<Inspection>(runtimeDirectory_, source,
                         {.operation = Isolation::Operation::Inspect,
                          .options = {.limits = limits, .bound = {}, .orientation = orientation},
                          .metadata = metadata},
                         cancelled, [](Isolation::Reply reply) { return std::move(reply.inspection); });
}
IsolatedResult<MetadataResult> IsolatedClient::readMetadata(QIODevice& source, const Limits& limits,
                                                            const std::atomic_bool& cancelled) const {
  return run<MetadataResult>(
      runtimeDirectory_, source,
      {.operation = Isolation::Operation::Metadata, .options = {.limits = limits, .bound = {}}, .metadata = true},
      cancelled, [](Isolation::Reply reply) { return std::move(reply.metadata); });
}
IsolatedResult<DecodeResult> IsolatedClient::decode(QIODevice& source, const DecodeOptions& options,
                                                    const std::atomic_bool& cancelled) const {
  return run<DecodeResult>(runtimeDirectory_, source,
                           {.operation = Isolation::Operation::Decode, .options = options, .metadata = true}, cancelled,
                           [](Isolation::Reply reply) { return std::move(reply.decoded); });
}
}  // namespace HolonightImages
