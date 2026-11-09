// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime.h"
#include "telemetry.h"
#include <QCoreApplication>
#include <QDir>
#include <QJsonDocument>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  Profile::events.reserve(512);
  std::string path;
  while (std::getline(std::cin, path)) {
    Profile::events.clear();
    const auto root = QString::fromStdString(path);
    const auto before = QDir("/proc/self/fd").entryList(QDir::AllEntries | QDir::NoDotAndDotDot).size();
    bool accepted = true;
    QElapsedTimer clock;
    clock.start();
    try {
      HolonightImages::Isolation::verifyRuntime(root);
    } catch (...) {
      accepted = false;
    }
    const auto elapsed = clock.nsecsElapsed();
    const auto after = QDir("/proc/self/fd").entryList(QDir::AllEntries | QDir::NoDotAndDotDot).size();
    const QJsonObject result{{"accepted", accepted}, {"total_ns", elapsed},
                             {"fd_before", before}, {"fd_after", after}, {"events", Profile::json()}};
    std::cout << QJsonDocument(result).toJson(QJsonDocument::Compact).constData() << '\n' << std::flush;
  }
}
