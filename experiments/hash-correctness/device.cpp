// SPDX-License-Identifier: GPL-3.0-or-later
#include "candidate.h"
#include <QCoreApplication>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <algorithm>
#include <cstring>
#include <iostream>
#include <unistd.h>

// Offset-triggered permanent faults; readData requests are diagnostic only.
class Controlled : public QIODevice {
public:
  QByteArray bytes;
  qint64 cursor = 0, limit;
  bool end;
  int terminal;
  QJsonArray reads;
  Controlled(QByteArray data, qint64 offset, bool atEnd, int result)
      : bytes(std::move(data)), limit(offset), end(atEnd), terminal(result) {}
  qint64 size() const override { return bytes.size(); }
  bool isSequential() const override { return false; }
  bool seek(qint64 offset) override {
    if (offset < 0 || offset > bytes.size() || !QIODevice::seek(offset)) return false;
    cursor = offset;
    return true;
  }
  bool atEnd() const override { return cursor >= limit && end; }
protected:
  qint64 readData(char* data, qint64 requested) override {
    qint64 count = std::min({requested, limit - cursor, qint64(997)});
    if (requested > 0 && cursor >= limit) {
      count = terminal;
      if (count < 0) setErrorString("injected offset fault");
    }
    if (count > 0) {
      std::memcpy(data, bytes.constData() + cursor, count);
      cursor += count;
    }
    reads.append(QJsonObject{{"requested", requested}, {"returned", count}});
    return count;
  }
  qint64 writeData(const char*, qint64) override { return -1; }
};

class ObservedFile : public QFile {
public:
  QJsonArray reads;
  qint64 delivered = 0, invalidateAt = -1;
  int borrowed = -1;
protected:
  qint64 readData(char* data, qint64 requested) override {
    auto request = requested;
    if (borrowed >= 0 && invalidateAt > delivered)
      request = std::min(request, invalidateAt - delivered);
    const auto count = QFile::readData(data, request);
    if (count > 0) delivered += count;
    // No descriptor-opening operations between close and the next hash read.
    if (borrowed >= 0 && delivered >= invalidateAt) {
      if (::close(borrowed) != 0) std::abort();
      borrowed = -1;
    }
    reads.append(QJsonObject{{"requested", requested}, {"engine_request", request},
                             {"returned", count}});
    return count;
  }
};

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  if (argc != 8) return 2;
  const QString variant = argv[1], kind = argv[2], path = argv[3];
  const qint64 offset = QString(argv[4]).toLongLong();
  const bool end = QString(argv[5]).toInt();
  const int terminal = QString(argv[6]).toInt();
  const bool unbuffered = QString(argv[7]).toInt();
  QFile input(path);
  if (!input.open(QIODevice::ReadOnly)) return 3;
  const auto bytes = input.readAll();
  input.close();
  Controlled controlled(bytes, offset, end, terminal);
  ObservedFile file;
  QIODevice* device = &controlled;
  QFile owner(path);
  if (kind == "file" || kind == "invalid-fd") {
    device = &file;
    if (!owner.open(QIODevice::ReadOnly) ||
        !file.open(owner.handle(), QIODevice::ReadOnly, QFileDevice::DontCloseHandle)) return 4;
    if (kind == "invalid-fd") {
      if (offset == 0) {
        if (::close(owner.handle()) != 0) return 5;
      } else {
        file.borrowed = owner.handle();
        file.invalidateAt = offset;
      }
    }
  } else if (kind != "closed") {
    controlled.open((kind == "write-only" ? QIODevice::WriteOnly : QIODevice::ReadOnly) |
                    (unbuffered ? QIODevice::Unbuffered : QIODevice::NotOpen));
  }
  QCryptographicHash hash(QCryptographicHash::Sha256);
  const bool completed = variant == "baseline" ? hash.addData(device)
                                               : HashCorrectness::addData(hash, device);
  const QJsonObject row{{"completed", completed}, {"digest", QString::fromLatin1(hash.result().toHex())},
    {"position", device->pos()}, {"at_end", device->atEnd()}, {"error", device->errorString()},
    {"file_error", device == &file ? int(file.error()) : -1},
    {"reads", device == &file ? file.reads : controlled.reads}};
  std::cout << QJsonDocument(row).toJson(QJsonDocument::Compact).constData() << '\n';
  // The owning QFile closes the stale descriptor only during destruction; nothing opens another fd.
}
