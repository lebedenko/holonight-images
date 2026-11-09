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
  if (!manifest["files"].isArray()) {
    throw ProtocolError("runtime inventory missing");
  }
  QSet<QString> expected{"manifest.json"};
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
}  // namespace HolonightImages::Isolation
