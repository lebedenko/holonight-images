// SPDX-License-Identifier: GPL-3.0-or-later
#include "verification.h"

#include "protocol.h"

#include <QCryptographicHash>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QSet>

#include <sys/stat.h>
#include <utility>

namespace HolonightImages::Isolation {
namespace {
constexpr qint64 runtimeByteCeiling = 128LL * 1024 * 1024;
constexpr qsizetype runtimeFileCeiling = 128;
QByteArray fileBytes(const QString& path, qint64 limit = controlCeiling) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) {
    return {};
  }
  auto bytes = file.read(limit + 1);
  return bytes.size() <= limit ? bytes : QByteArray{};
}
}  // namespace
// Keep the ordered security/lifecycle checks together for auditing.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
QStringList verifyRuntime(const QString& root) {
  if (!QDir::isAbsolutePath(root) || QFileInfo(root).isSymLink()) {
    throw ProtocolError("runtime must be an explicit absolute directory");
  }
  struct stat manifestInfo{};
  if ((lstat(QFile::encodeName(root + "/manifest.json").constData(), &manifestInfo) != 0) ||
      !S_ISREG(manifestInfo.st_mode) || (manifestInfo.st_mode & 07777) != 0644) {
    throw ProtocolError("runtime manifest missing or invalid");
  }
  const auto manifest = parseControl(fileBytes(root + "/manifest.json"));
  integer(manifest, "version", 1, 1);
  if (manifest.contains("sessionProtocol")) {
    integer(manifest, "sessionProtocol", 0, 1);
  }
  if (!manifest["files"].isArray()) {
    throw ProtocolError("runtime inventory missing");
  }
  QSet<QString> expected{"manifest.json"};
  qint64 totalBytes = manifestInfo.st_size;
  if (manifest["files"].toArray().size() >= runtimeFileCeiling) {
    throw ProtocolError("runtime file count limit");
  }
  QSet<QString> dirs;
  QStringList binds;
  for (auto value : manifest["files"].toArray()) {
    if (!value.isObject()) {
      throw ProtocolError("runtime file record");
    }
    const auto record = value.toObject();
    const auto path = record["path"].toString();
    if (!path.startsWith("usr/") || QDir::cleanPath(path) != path || path.contains(QChar::Null) ||
        expected.contains(path)) {
      throw ProtocolError("runtime path or collision");
    }
    expected.insert(path);
    auto parent = QFileInfo(path).path();
    while (parent != ".") {
      dirs.insert(parent);
      parent = QFileInfo(parent).path();
    }
    const auto absolute = root + "/" + path;
    struct stat info{};
    const auto mode = integer(record, "mode", 0644, 0755);
    if ((mode != 0644 && mode != 0755) || (lstat(QFile::encodeName(absolute).constData(), &info) != 0) ||
        !S_ISREG(info.st_mode) || std::cmp_not_equal((info.st_mode & 07777), mode) ||
        info.st_size != integer(record, "size", 0, 1024LL * 1024 * 1024)) {
      throw ProtocolError("runtime file attributes changed");
    }
    if (info.st_size > runtimeByteCeiling - totalBytes) {
      throw ProtocolError("runtime aggregate byte limit");
    }
    totalBytes += info.st_size;
    QFile file(absolute);
    QCryptographicHash hash(QCryptographicHash::Sha256);
    if (!file.open(QIODevice::ReadOnly) || !hash.addData(&file) ||
        QString::fromLatin1(hash.result().toHex()) != record["sha256"].toString()) {
      throw ProtocolError("runtime file hash changed");
    }
    binds << "--ro-bind" << absolute << "/" + path;
  }
  for (const auto* required :
       {"usr/libexec/holonight-images-helper", "usr/lib/qt6/plugins/imageformats/libqgif.so",
        "usr/lib/qt6/plugins/imageformats/libqjpeg.so", "usr/lib/qt6/plugins/imageformats/libqtiff.so",
        "usr/lib/qt6/plugins/imageformats/libqwebp.so"}) {
    if (!expected.contains(required)) {
      throw ProtocolError("runtime inventory incomplete");
    }
  }
  QDirIterator entries(root, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden | QDir::System,
                       QDirIterator::Subdirectories);
  while (entries.hasNext()) {
    const auto name = QDir(root).relativeFilePath(entries.next());
    const auto info = entries.fileInfo();
    if (info.isSymLink() || (info.isDir() ? !dirs.contains(name) : !info.isFile() || !expected.contains(name))) {
      throw ProtocolError("unexpected runtime entry");
    }
  }
  return binds;
}

void verifyProtectedRuntime(const QString& root) {
  if (!QDir::isAbsolutePath(root) || QDir::cleanPath(root) != root) {
    throw ProtocolError("protected runtime requires a clean absolute path");
  }
  auto check = [](const QString& path, bool directory) {
    struct stat info{};
    if (lstat(QFile::encodeName(path).constData(), &info) != 0 || info.st_uid != 0 || (info.st_mode & 0022) != 0 ||
        (directory ? !S_ISDIR(info.st_mode) : !S_ISREG(info.st_mode))) {
      throw ProtocolError("runtime is not protected by root ownership and modes");
    }
  };
  auto ancestor = root;
  while (true) {
    check(ancestor, true);
    if (ancestor == "/") {
      break;
    }
    ancestor = QFileInfo(ancestor).path();
  }
  QDirIterator entries(root, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden | QDir::System,
                       QDirIterator::Subdirectories);
  while (entries.hasNext()) {
    const auto path = entries.next();
    check(path, entries.fileInfo().isDir());
  }
}
}  // namespace HolonightImages::Isolation
