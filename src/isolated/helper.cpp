// SPDX-License-Identifier: GPL-3.0-or-later
#include "protocol.h"
#include "runtime.h"

#include <QBuffer>
#include <QCoreApplication>
#include <QFile>
#include <QImageReader>
#include <QtEndian>

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
}  // namespace
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
  if (argc == 3 && QByteArray(arguments[1]) == "--verify-runtime") {
    try {
      verifyRuntime(QString::fromLocal8Bit(arguments[2]));
      return 0;
    } catch (...) {
      return 77;
    }
  }
  QCoreApplication::setLibraryPaths({"/usr/lib/qt6/plugins"});
  QImageReader::setAllocationLimit(256);
  try {
    QFile input;
    QFile output;
    if (!input.open(stdin, QIODevice::ReadOnly) || !output.open(stdout, QIODevice::WriteOnly)) {
      return 75;
    }
    if (output.write("R", 1) != 1 || !output.flush()) {
      return 76;
    }
    const auto size = qFromBigEndian<quint32>(read(input, 4).constData());
    if ((size == 0U) || size > controlCeiling) {
      return 72;
    }
    qint64 count = 0;
    const auto request = parseRequest(parseControl(read(input, size)), count);
    auto bytes = read(input, count);
    QBuffer device(&bytes);
    device.open(QIODevice::ReadOnly);
    const std::atomic_bool cancelled{false};
    Reply reply;
    // Sniff and reject formats outside this milestone before invoking the provider.
    const auto format = canonicalFormat(QImageReader::imageFormat(&device));
    const bool qualified = QList<QByteArray>{"png", "jpeg", "bmp", "tiff", "webp", "gif"}.contains(format);
    if (!qualified) {
      reply.inspection.outcome = Outcome::Unsupported;
      reply.metadata.outcome = Outcome::Unsupported;
      reply.decoded.outcome = Outcome::Unsupported;
      reply.decoded.inspection.outcome = Outcome::Unsupported;
    } else if (request.operation == Operation::Inspect) {
      reply.inspection = HolonightImages::inspect(device, request.options.limits, cancelled,
                                                  request.options.orientation, request.metadata);
    } else if (request.operation == Operation::Metadata) {
      reply.metadata = HolonightImages::readMetadata(device, request.options.limits, cancelled);
    } else {
      reply.decoded = HolonightImages::decode(device, request.options, cancelled);
    }
    QByteArray pixels;
    auto control = replyControl(reply, request.operation, pixels);
    auto header = frame(control);
    if (output.write(header) != header.size() || output.write(pixels) != pixels.size() || !output.flush()) {
      return 73;
    }
    if (read(input, 1) != "A") {
      return 78;
    }
    return 0;
  } catch (const std::exception&) {
    return 74;
  }
}
