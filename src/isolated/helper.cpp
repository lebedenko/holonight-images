// SPDX-License-Identifier: GPL-3.0-or-later
#include "protocol.h"
#include "verification.h"

#include <QBuffer>
#include <QCoreApplication>
#include <QFile>
#include <QImageReader>
#include <QtEndian>

#include <cstdio>
#include <poll.h>
#include <span>
#include <unistd.h>

using namespace HolonightImages;
using namespace HolonightImages::Isolation;
namespace {
QByteArray read(QFile& file, qint64 count) {
  QByteArray bytes;
  while (bytes.size() < count) {
    auto part = file.read(qMin<qint64>(65536, count - bytes.size()));
    if (part.isEmpty()) {
      throw ProtocolError("request EOF");
    }
    bytes += part;
  }
  return bytes;
}
bool transactionCommand(const QJsonObject& record, const Request& request, qint64 count, int sequence,
                        bool sourceDecoded, int& candidates, qint64 retainedSize) {
  integer(record, "transactionVersion", 1, 1);
  integer(record, "sequence", sequence, sequence);
  if (!record["retainedSource"].isBool()) {
    throw ProtocolError("invalid retained source flag");
  }
  const bool retained = record["retainedSource"].toBool();
  if (sequence == 0) {
    if (request.operation != Operation::Inspect || retained) {
      throw ProtocolError("transaction must start with source inspection");
    }
  } else if (request.operation != Operation::Decode || sourceDecoded || (!retained && ++candidates > 4)) {
    throw ProtocolError("invalid transaction command sequence");
  }
  if (retained && (count != 0 || retainedSize > request.options.limits.inputBytes)) {
    throw ProtocolError("unexpected retained source payload");
  }
  return retained;
}
Reply execute(const Request& request, QByteArray& bytes, bool cachedPng) {
  QBuffer device(&bytes);
  device.open(QIODevice::ReadOnly);
  const std::atomic_bool cancelled{false};
  Reply reply;
  // Sniff and reject formats outside this milestone before invoking the provider.
  const auto format = canonicalFormat(QImageReader::imageFormat(&device));
  const bool qualified = QList<QByteArray>{"png", "jpeg", "bmp", "tiff", "webp", "gif"}.contains(format);
  if (!qualified || (cachedPng && format != "png")) {
    reply.inspection.outcome = Outcome::Unsupported;
    reply.metadata.outcome = Outcome::Unsupported;
    reply.decoded.outcome = Outcome::Unsupported;
    reply.decoded.inspection.outcome = Outcome::Unsupported;
  } else if (request.operation == Operation::Inspect) {
    reply.inspection = HolonightImages::inspect(device, request.options.limits, cancelled, request.options.orientation,
                                                request.metadata);
  } else if (request.operation == Operation::Metadata) {
    reply.metadata = HolonightImages::readMetadata(device, request.options.limits, cancelled);
  } else {
    reply.decoded = HolonightImages::decode(device, request.options, cancelled);
  }
  return reply;
}
// Scope all transaction resources together; acknowledgement follows its destruction.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
int serve(QFile& input, QFile& output, bool session = false, int transaction_id = 0) {
  QByteArray retainedBytes;
  bool transaction = false;
  bool sourceDecoded = false;
  int sequence = 0;
  int candidates = 0;
  QByteArray prefix;
  while (true) {
    const auto size = qFromBigEndian<quint32>((prefix + read(input, 4 - prefix.size())).constData());
    if ((size == 0U) || size > controlCeiling) {
      return 72;
    }
    qint64 count = 0;
    const auto record = parseControl(read(input, size));
    if (session) {
      integer(record, "sessionVersion", 1, 1);
      integer(record, "transactionId", transaction_id, transaction_id);
      integer(record, "sequence", sequence, sequence);
      if (record.contains("command")) {
        if (sequence == 0 || record.size() != 4 || record["command"] != "complete") {
          throw ProtocolError("invalid session completion command");
        }
        // Returning destroys source bytes, reply pixels, devices and readers.
        // The outer loop acknowledges only after this scope has been destroyed.
        return -sequence - 1;
      }
      if (!record.contains("transactionVersion")) {
        throw ProtocolError("session requires source transaction");
      }
    }
    const auto request = parseRequest(record, count);
    if (sequence == 0) {
      transaction = record.contains("transactionVersion");
    }
    bool retained = false;
    if (transaction) {
      retained = transactionCommand(record, request, count, sequence, sourceDecoded, candidates, retainedBytes.size());
      sourceDecoded = retained;
    }
    auto bytes = retained ? retainedBytes : read(input, count);
    if (transaction && sequence == 0) {
      retainedBytes = bytes;
    }
    auto reply = execute(request, bytes, transaction && sequence > 0 && !retained);
    QByteArray pixels;
    auto control = replyControl(reply, request.operation, pixels);
    if (transaction) {
      control["transactionVersion"] = 1;
      control["sequence"] = sequence;
    }
    if (session) {
      control["sessionVersion"] = 1;
      control["transactionId"] = transaction_id;
    }
    const auto header = frame(control);
    if (output.write(header) != header.size() || output.write(pixels) != pixels.size() || !output.flush()) {
      return 73;
    }
    prefix = read(input, 1);
    if (!session && prefix == "A") {
      return 0;
    }
    if (!transaction) {
      return 78;
    }
    ++sequence;
  }
}
}  // namespace
// Keep the trusted gate and validation-only entrypoints adjacent to protocol dispatch.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
int main(int argc, char** argv) {
  const std::span<char*> arguments(argv, static_cast<size_t>(argc) + 1);
  // The trusted launcher gate never interprets image bytes. Parent releases it
  // only after observing the scope's actual memory and swap limits.
  if (argc > 2 && QByteArray(arguments[1]) == "--gate") {
    pollfd descriptor{.fd = STDIN_FILENO, .events = POLLIN, .revents = 0};
    char release = 0;
    if (poll(&descriptor, 1, 15000) != 1 || ::read(STDIN_FILENO, &release, 1) != 1 || release != 'G') {
      return 70;
    }
    execv(arguments[2], arguments.subspan(2).data());
    return 71;
  }
  QCoreApplication app(argc, argv);
  if (argc == 2 && QByteArray(arguments[1]) == "--session-protocol-version") {
    std::fputs("1\n", stdout);
    return 0;
  }
  if (argc == 3 &&
      (QByteArray(arguments[1]) == "--verify-runtime" || QByteArray(arguments[1]) == "--verify-protected-runtime")) {
    try {
      const auto root = QString::fromLocal8Bit(arguments[2]);
      if (QByteArray(arguments[1]) == "--verify-protected-runtime") {
        verifyProtectedRuntime(root);
      }
      verifyRuntime(root);
      return 0;
    } catch (...) {
      return 77;
    }
  }
  QCoreApplication::setLibraryPaths({"/usr/lib/qt6/plugins"});
  QImageReader::setAllocationLimit(qtAllocationMiB);
  try {
    QFile input;
    QFile output;
    if (!input.open(stdin, QIODevice::ReadOnly) || !output.open(stdout, QIODevice::WriteOnly)) {
      return 75;
    }
    if (output.write("R", 1) != 1 || !output.flush()) {
      return 76;
    }
    const bool session = argc == 2 && QByteArray(arguments[1]) == "--session";
    if (!session) {
      return serve(input, output);
    }
    const auto readiness = frame(QJsonObject{{"sessionVersion", 1}, {"command", "ready"}});
    if (output.write(readiness) != readiness.size() || !output.flush()) {
      return 76;
    }
    for (int transaction_id = 1; transaction_id < INT_MAX; ++transaction_id) {
      const auto completed = serve(input, output, true, transaction_id);
      if (completed >= 0) {
        return completed;
      }
      const auto acknowledgement = frame(QJsonObject{{"sessionVersion", 1},
                                                     {"transactionId", transaction_id},
                                                     {"sequence", -completed - 1},
                                                     {"command", "completed"}});
      if (output.write(acknowledgement) != acknowledgement.size() || !output.flush()) {
        return 73;
      }
    }
    return 78;

  } catch (const std::exception&) {
    return 74;
  }
}
