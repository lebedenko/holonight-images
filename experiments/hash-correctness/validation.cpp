// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime.h"
#include <QCoreApplication>
#include <QJsonDocument>
#include <QJsonObject>
#include <iostream>
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  if (argc != 2) return 2;
  bool accepted = true;
  try {
    HolonightImages::Isolation::verifyRuntime(QString::fromLocal8Bit(argv[1]));
  } catch (...) {
    accepted = false;
  }
  std::cout << QJsonDocument(QJsonObject{{"accepted", accepted}})
                   .toJson(QJsonDocument::Compact).constData() << '\n';
}
