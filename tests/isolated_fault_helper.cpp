// SPDX-License-Identifier: GPL-3.0-or-later
// Deliberately hostile test executable; never installed in a production bundle.
#include "../src/isolated/protocol.h"

#include <QCoreApplication>
#include <QFile>
#include <QThread>
#include <QtEndian>

#include <csignal>
#include <cstdio>
#include <poll.h>
#include <span>
#include <sys/prctl.h>
#include <unistd.h>
using namespace HolonightImages;
using namespace HolonightImages::Isolation;
namespace {
QByteArray read(QFile& file, qint64 size) {
  QByteArray data;
  while (data.size() < size) {
    auto part = file.read(size - data.size());
    if (part.isEmpty()) {
      _exit(90);
    }
    data += part;
  }
  return data;
}
QByteArray readMode(QFile& input, qint64 length) {
  const auto prefix = read(input, qMin<qint64>(12, length));
  if (prefix == "backpressure") {
    // Signal after reading only the selector; the remaining payload exceeds pipe
    // capacity. Never consume it, so cancellation must interrupt request writes.
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
    prctl(PR_SET_NAME, "hn-test-ready");
    for (;;) {
      pause();
    }
  }
  return prefix + read(input, length - prefix.size());
}
int completePayload(const QByteArray& payload, Operation operation, QFile& input, QFile& out) {
  for (qsizetype i = 8; i < payload.size(); ++i) {
    if (payload[i] != static_cast<char>(i % 251)) {
      return 94;
    }
  }
  Reply reply;
  reply.decoded.outcome = Outcome::Unsupported;
  reply.decoded.inspection.outcome = Outcome::Unsupported;
  QByteArray pixels;
  const auto header = frame(replyControl(reply, operation, pixels));
  if (out.write(header) != header.size() || !out.flush() || read(input, 1) != "A") {
    return 95;
  }
  return 0;
}
int sessionFault(QFile& input, QFile& out) {
  out.write(frame(QJsonObject{{"sessionVersion", 1}, {"command", "ready"}}));
  out.flush();
  const auto count = qFromBigEndian<quint32>(read(input, 4).constData());
  if (!count || count > controlCeiling) {
    return 92;
  }
  const auto record = parseControl(read(input, count));
  qint64 bytes = 0;
  const auto request = parseRequest(record, bytes);
  const auto mode = read(input, bytes);
  if (mode == "session-crash") {
    return 93;
  }
  if (mode == "session-hang") {
    for (;;) {
      pause();
    }
  }
  if (mode == "session-malformed") {
    out.write(QByteArray::fromHex("ffffffff"));
    out.flush();
    return 93;
  }
  if (mode == "session-descendant" && fork() == 0) {
    signal(SIGTERM, SIG_IGN);
    prctl(PR_SET_NAME, "hn-session-kid");
    for (;;) {
      pause();
    }
  }
  Reply reply;
  reply.inspection.outcome = Outcome::Unsupported;
  QByteArray pixels;
  auto response = replyControl(reply, request.operation, pixels);
  response["transactionVersion"] = 1;
  response["sessionVersion"] = 1;
  response["transactionId"] = mode == "session-identity" ? 2 : 1;
  response["sequence"] = mode == "session-sequence" ? 1 : 0;
  out.write(frame(response));
  out.flush();
  const auto completion_size = qFromBigEndian<quint32>(read(input, 4).constData());
  if (!completion_size || completion_size > controlCeiling) {
    return 92;
  }
  const auto completion = parseControl(read(input, completion_size));
  integer(completion, "transactionId", 1, 1);
  integer(completion, "sequence", 1, 1);
  if (completion["command"] != "complete") {
    return 92;
  }
  out.write(frame(QJsonObject{{"sessionVersion", 1},
                              {"transactionId", mode == "session-ack-identity" ? 2 : 1},
                              {"sequence", 1},
                              {"command", "completed"}}));
  out.flush();
  if (mode == "session-idle-output") {
    QThread::msleep(20);
    const QByteArray flood(65536, 'x');
    while (out.write(flood) == flood.size() && out.flush()) {
    }
    return 93;
  }
  if (mode == "session-idle-exit") {
    QThread::msleep(20);
    return 0;
  }
  for (;;) {
    pause();
  }
}
}  // namespace
int main(int argc, char** argv) {
  const std::span<char*> arguments(argv, static_cast<size_t>(argc) + 1);
  if (argc > 2 && QByteArray(arguments[1]) == "--gate") {
    pollfd descriptor{.fd = 0, .events = POLLIN, .revents = 0};
    char release = 0;
    if (poll(&descriptor, 1, 15000) != 1 || ::read(0, &release, 1) != 1 || release != 'G') {
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
  QFile input;
  QFile out;
  if (!input.open(stdin, QIODevice::ReadOnly) || !out.open(stdout, QIODevice::WriteOnly)) {
    return 91;
  }
#ifdef HN_TEST_STARTUP_TIMEOUT
  if (argc == 2 && QByteArray(arguments[1]) == "--session") {
    for (;;) {
      pause();
    }
  }
#endif
  if (out.write("R", 1) != 1 || !out.flush()) {
    return 76;
  }
  if (argc == 2 && QByteArray(arguments[1]) == "--session") {
    return sessionFault(input, out);
  }
  const auto size = qFromBigEndian<quint32>(read(input, 4).constData());
  if (size > controlCeiling) {
    return 92;
  }
  qint64 length = 0;
  const auto record = parseControl(read(input, size));
  auto request = parseRequest(record, length);
  auto mode = readMode(input, length);
  if (mode.startsWith("txn-")) {
    integer(record, "transactionVersion", 1, 1);
    integer(record, "sequence", 0, 0);
    Reply reply;
    reply.inspection.outcome = Outcome::Unsupported;
    QByteArray pixels;
    auto response = replyControl(reply, Operation::Inspect, pixels);
    response["transactionVersion"] = 1;
    response["sequence"] = 0;
    out.write(frame(response));
    out.flush();
    const auto nextSize = qFromBigEndian<quint32>(read(input, 4).constData());
    if (nextSize == 0 || nextSize > controlCeiling) {
      return 92;
    }
    request = parseRequest(parseControl(read(input, nextSize)), length);
    read(input, length);
    mode = mode.mid(4);
    if (mode == "trailing" || mode == "identity") {
      Reply decoded;
      decoded.decoded.outcome = Outcome::Unsupported;
      decoded.decoded.inspection.outcome = Outcome::Unsupported;
      auto control = replyControl(decoded, Operation::Decode, pixels);
      control["transactionVersion"] = 1;
      control["sequence"] = mode == "identity" ? 7 : 1;
      out.write(frame(control));
      if (mode == "trailing") {
        out.write("trailing");
      }
      out.flush();
      read(input, 1);
      return 0;
    }
  }
  if (mode.startsWith("payload:")) {
    return completePayload(mode, request.operation, input, out);
  }
  if (mode == "crash") {
    return 93;
  }
  if (mode == "malformed") {
    out.write(QByteArray::fromHex("ffffffff"));
    out.flush();
    return 0;
  }
  if (mode == "partial") {
    out.write(QByteArray::fromHex("00000010"));
    out.write("{");
    out.flush();
    return 0;
  }
  if (mode == "descendant" || mode == "race") {
    if (fork() == 0) {
      signal(SIGTERM, SIG_IGN);
      // Linux fixture readiness uses the required variadic syscall wrapper.
      // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
      prctl(PR_SET_NAME, "hn-test-child");
      for (;;) {
        pause();
      }
    }
    // NOLINTNEXTLINE(cppcoreguidelines-pro-type-vararg)
    prctl(PR_SET_NAME, "hn-test-ready");
  }
  if (mode == "race") {
    Reply reply;
    reply.decoded.outcome = Outcome::Unsupported;
    reply.decoded.inspection.outcome = Outcome::Unsupported;
    QByteArray pixels;
    out.write(frame(replyControl(reply, request.operation, pixels)));
    out.flush();
  }
  // Hang, cancellation after helper readiness, or a reply/cleanup cancellation race.
  for (;;) {
    pause();
  }
}
