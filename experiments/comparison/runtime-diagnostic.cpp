// SPDX-License-Identifier: GPL-3.0-or-later
#include <QBuffer>
#include <QCoreApplication>
#include <QFile>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>
#include <QStandardPaths>
#include <QTcpSocket>
#include <QtEndian>

#include <cstdio>
#include <dlfcn.h>
extern "C" char* comparison_config();
extern "C" void comparison_config_free(char*);
int main(int argc, char** argv) {
  QCoreApplication application(argc, argv);
  const auto send = [](const QJsonObject& result) {
    const auto bytes = QJsonDocument(result).toJson(QJsonDocument::Compact);
    const auto size = qToBigEndian(quint32(bytes.size()));
    std::fwrite(&size, sizeof(size), 1, stdout);
    std::fwrite(bytes.constData(), 1, size_t(bytes.size()), stdout);
    std::fflush(stdout);
  };
  while (true) {
    quint32 length = 0;
    if (std::fread(&length, sizeof(length), 1, stdin) != 1) break;
    length = qFromBigEndian(length);
    if (length == 0 || length > 65536) return 2;
    QByteArray control(qsizetype(length), Qt::Uninitialized);
    if (std::fread(control.data(), 1, length, stdin) != length) return 2;
    const auto request = QJsonDocument::fromJson(control).object();
    if (request["bytes"].toInt() != 0) return 2;
    if (request["op"] == "close") {
      send({{"outcome", "closed"}, {"bytes", 0}});
      break;
    }
    QJsonObject result{{"outcome", "diagnostic"}, {"bytes", 0}};
    QJsonObject environment;
    for (const auto* key : {"PATH", "LD_PRELOAD", "LD_AUDIT", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH",
                            "QT_QPA_PLATFORM_PLUGIN_PATH", "GLYCIN_DATA_DIR", "GLYCIN_DISABLE_SANDBOX", "XDG_DATA_HOME",
                            "XDG_DATA_DIRS", "XDG_CONFIG_HOME", "XDG_CONFIG_DIRS"}) {
      environment[key] = QString::fromLocal8Bit(qgetenv(key));
    }
    result["environment"] = environment;
    QProcess marker;
    marker.start("hn-runtime-marker", {});
    marker.waitForFinished(2000);
    result["path_token"] = QString::fromUtf8(marker.readAllStandardOutput()).trimmed();
    if (void* library = dlopen("libholonight_runtime_control_7e40.so", RTLD_NOW)) {
      const auto token = reinterpret_cast<const char* (*)()>(dlsym(library, "holonight_runtime_control"));
      if (token) result["library_token"] = token();
      dlclose(library);
    }
    QByteArray bytes("HNCONTROL");
    QBuffer buffer(&bytes);
    buffer.open(QIODevice::ReadOnly);
    QImageReader reader(&buffer, "hncontrol");
    const auto image = reader.read();
    result["plugin_pixel"] = image.isNull() ? QJsonArray{}
                                            : QJsonArray{image.pixelColor(0, 0).red(), image.pixelColor(0, 0).green(),
                                                         image.pixelColor(0, 0).blue(), image.pixelColor(0, 0).alpha()};
    const auto config = QStandardPaths::locate(QStandardPaths::GenericConfigLocation, "holonight-runtime-control.conf");
    QFile configFile(config);
    result["configuration_token"] =
        configFile.open(QIODevice::ReadOnly) ? QString::fromUtf8(configFile.readAll()).trimmed() : QString{};
    char* glycin = comparison_config();
    result["glycin_loader"] = QString::fromUtf8(glycin ? glycin : "");
    comparison_config_free(glycin);
    if (argc > 1) {
      QFile host(QString::fromLocal8Bit(argv[1]));
      result["host_file"] = host.open(QIODevice::ReadOnly) ? QString::fromUtf8(host.readAll()) : QString{};
    }
    if (argc > 2) {
      QTcpSocket socket;
      socket.connectToHost("127.0.0.1", QString::fromLocal8Bit(argv[2]).toUShort());
      result["network_reachable"] = socket.waitForConnected(1000);
    }
    send(result);
  }
}
