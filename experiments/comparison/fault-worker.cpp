// SPDX-License-Identifier: GPL-3.0-or-later
// Deliberately hostile private protocol peer; never linked into a candidate.
#include <QCoreApplication>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>

#include <arpa/inet.h>
#include <csignal>
#include <cstdio>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  const auto args = app.arguments();
  const auto mode = args.value(1);
  if (mode == "crash") return 42;
  if (mode == "hang") {
    for (;;) pause();
  }
  if (mode.startsWith("cancel-")) {
    if (mode == "cancel-input") {
      std::fprintf(stderr, "ACK blocked-input\n");
      std::fflush(stderr);
      for (;;) pause();
    }
    if (mode == "cancel-descendant") {
      std::signal(SIGTERM, SIG_IGN);
      const auto child = fork();
      if (child == 0) {
        std::signal(SIGTERM, SIG_IGN);
        std::fprintf(stderr, "ACK descendant-ready\n");
        std::fflush(stderr);
        for (;;) pause();
      }
    }
    quint32 wire = 0;
    if (std::fread(&wire, 1, 4, stdin) != 4) return 2;
    const auto length = qFromBigEndian(wire);
    if (length > 65536) return 2;
    QByteArray request(int(length), '\0');
    if (std::fread(request.data(), 1, length, stdin) != length) return 2;
    const auto count = QJsonDocument::fromJson(request).object().value("bytes").toInt();
    for (int i = 0; i < count; ++i)
      if (std::getc(stdin) == EOF) return 2;
    std::fprintf(stderr, "ACK dispatched\n");
    std::fflush(stderr);
    if (mode == "cancel-eof") return 0;
    if (mode == "cancel-malformed") {
      const quint32 header = qToBigEndian(quint32(1));
      std::fwrite(&header, 1, 4, stdout);
      std::fwrite("!", 1, 1, stdout);
      std::fflush(stdout);
    } else if (mode == "cancel-control") {
      const quint32 header = qToBigEndian(quint32(100));
      std::fwrite(&header, 1, 4, stdout);
      std::fwrite("{", 1, 1, stdout);
      std::fflush(stdout);
      std::fprintf(stderr, "ACK partial-control\n");
      std::fflush(stderr);
    } else if (mode == "cancel-pixels") {
      const auto control = QByteArray("{\"bytes\":8,\"width\":2,\"height\":1,\"stride\":8}");
      const quint32 header = qToBigEndian(quint32(control.size()));
      std::fwrite(&header, 1, 4, stdout);
      std::fwrite(control.data(), 1, size_t(control.size()), stdout);
      std::fwrite("x", 1, 1, stdout);
      std::fflush(stdout);
      std::fprintf(stderr, "ACK partial-pixels\n");
      std::fflush(stderr);
    }
    for (;;) pause();
  }
  // Synchronize probes and malformed responses with the request being tested.
  quint32 requestWire = 0;
  if (std::fread(&requestWire, 1, 4, stdin) != 4) return 2;
  const auto requestLength = qFromBigEndian(requestWire);
  if (requestLength > 65536) return 2;
  for (quint32 i = 0; i < requestLength; ++i)
    if (std::getc(stdin) == EOF) return 2;
  QJsonObject response{{"bytes", 0}, {"outcome", "probe"}};
  if (mode == "oversize") response["bytes"] = 256 * 1024 * 1024 + 1;
  if (mode == "stride") {
    response["bytes"] = 8;
    response["width"] = 2;
    response["height"] = 2;
    response["stride"] = 4;
  }
  if (mode == "probe") {
    QFile original(args.value(2));
    response["original_readable"] = original.open(QIODevice::ReadOnly);
    const int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    sockaddr_in address{};
    address.sin_family = AF_INET;
    address.sin_port = htons(args.value(3).toUShort());
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    response["host_network_reachable"] =
        fd >= 0 && connect(fd, reinterpret_cast<sockaddr*>(&address), sizeof address) == 0;
    if (fd >= 0) close(fd);
  }
  auto json = QJsonDocument(response).toJson(QJsonDocument::Compact);
  quint32 length = qToBigEndian(quint32(mode == "control" ? 65537 : json.size()));
  std::fwrite(&length, 1, sizeof length, stdout);
  std::fwrite(json.constData(), 1, size_t(json.size()), stdout);
  std::fflush(stdout);
  return 0;
}
