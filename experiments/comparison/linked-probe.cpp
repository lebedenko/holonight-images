// SPDX-License-Identifier: GPL-3.0-or-later
#include "linked-acquisition.h"

#include <QCoreApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <csignal>
#include <cstdio>

namespace {
std::atomic_bool cancelled{false};
void cancel(int) { cancelled.store(true); }
QJsonObject identity(const struct stat& value) {
  return {{"device", QString::number(value.st_dev)},
          {"inode", QString::number(value.st_ino)},
          {"mode", QString::number(value.st_mode)},
          {"size", QString::number(value.st_size)},
          {"mtime_seconds", QString::number(value.st_mtim.tv_sec)},
          {"mtime_ns", QString::number(value.st_mtim.tv_nsec)},
          {"ctime_seconds", QString::number(value.st_ctim.tv_sec)},
          {"ctime_ns", QString::number(value.st_ctim.tv_nsec)}};
}
}  // namespace
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  if (argc != 4) return 2;
  std::signal(SIGTERM, cancel);
  std::signal(SIGINT, cancel);
  bool baseOk = false, mainOk = false;
  const int base = QString::fromLocal8Bit(argv[1]).toInt(&baseOk);
  const int main = QString::fromLocal8Bit(argv[2]).toInt(&mainOk);
  if (!baseOk || !mainOk) return 2;
  Comparison::LinkedAcquisition acquisition(base, main, QString::fromUtf8(argv[3]));
  auto captured = acquisition.captureMain(cancelled);
  if (captured.outcome != Comparison::CaptureOutcome::Success) {
    std::fprintf(stderr, "main acquisition failed: %d (openat2 required)\n", int(captured.outcome));
    return 1;
  }
  std::printf("%lld\n", static_cast<long long>(captured.bytes.size()));
  std::fwrite(captured.bytes.constData(), 1, size_t(captured.bytes.size()), stdout);
  std::fflush(stdout);
  QFile input;
  if (!input.open(stdin, QIODevice::ReadOnly, QFileDevice::DontCloseHandle)) return 1;
  const auto line = input.readLine(65538);
  QJsonParseError error;
  const auto document = QJsonDocument::fromJson(line, &error);
  if (line.size() > 65536 || !line.endsWith('\n') || error.error != QJsonParseError::NoError || !document.isObject() ||
      !document.object().value("paths").isArray())
    return 1;
  QStringList paths;
  for (const auto& entry : document.object().value("paths").toArray()) {
    if (!entry.isString()) return 1;
    paths.append(entry.toString());
  }
  const auto outcome = acquisition.complete(paths, cancelled);
  if (outcome != Comparison::CaptureOutcome::Success) {
    std::fprintf(stderr, "resource acquisition failed: %d (openat2 required)\n", int(outcome));
    return 1;
  }
  QJsonArray entries;
  for (auto it = acquisition.files().cbegin(); it != acquisition.files().cend(); ++it)
    entries.append(QJsonObject{{"path", it.key()},
                               {"bytes", it.value().size()},
                               {"identity", identity(acquisition.identities().value(it.key()))}});
  const auto record = QJsonDocument(QJsonObject{{"files", entries}}).toJson(QJsonDocument::Compact);
  if (record.size() > 65536 || cancelled.load()) return 1;
  std::fwrite(record.constData(), 1, size_t(record.size()), stdout);
  std::putchar('\n');
  for (const auto& data : acquisition.files()) std::fwrite(data.constData(), 1, size_t(data.size()), stdout);
  return std::ferror(stdout) ? 1 : 0;
}
