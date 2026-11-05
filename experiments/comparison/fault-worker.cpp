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
