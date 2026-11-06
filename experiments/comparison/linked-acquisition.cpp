// SPDX-License-Identifier: GPL-3.0-or-later
#include "linked-acquisition.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>

#include <fcntl.h>
#include <linux/openat2.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace Comparison {
namespace {
bool validPath(const QString& path) {
  if (path.isEmpty() || path.toUtf8().size() > 1024 || path != path.trimmed() ||
      QString::fromUtf8(path.toUtf8()) != path)
    return false;
  for (const auto c : path) {
    if (c.unicode() < 32 || c.unicode() == 127 || QStringLiteral("%\\?#:").contains(c)) return false;
  }
  for (const auto& part : path.split('/')) {
    if (part.isEmpty() || part == "." || part == "..") return false;
  }
  return true;
}
int openBeneath(int base, const QString& name) {
  const auto encoded = name.toUtf8();
  const open_how how{.flags = O_RDONLY | O_CLOEXEC | O_NONBLOCK,
                     .mode = 0,
                     .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV};
  // ENOSYS/EINVAL are explicit failure, never a pathname fallback.
  return int(syscall(SYS_openat2, base, encoded.constData(), &how, sizeof how));
}
bool regular(int fd, struct stat& record) { return fstat(fd, &record) == 0 && S_ISREG(record.st_mode); }
bool same(const struct stat& a, const struct stat& b) {
  return a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_mode == b.st_mode && a.st_size == b.st_size &&
         a.st_mtim.tv_sec == b.st_mtim.tv_sec && a.st_mtim.tv_nsec == b.st_mtim.tv_nsec &&
         a.st_ctim.tv_sec == b.st_ctim.tv_sec && a.st_ctim.tv_nsec == b.st_ctim.tv_nsec;
}
bool revalidate(int base, const QString& path, const struct stat& expected) {
  const int fd = openBeneath(base, path);
  if (fd < 0) return false;
  struct stat actual{};
  const bool matches = regular(fd, actual) && same(expected, actual);
  close(fd);
  return matches;
}
CaptureResult readFile(int fd, qint64 limit, const std::atomic_bool& cancelled, struct stat& identity) {
  if (!regular(fd, identity)) return {CaptureOutcome::IoFailure, {}};
  QFile device;
  if (!device.open(fd, QIODevice::ReadOnly, QFileDevice::DontCloseHandle)) return {CaptureOutcome::IoFailure, {}};
  auto result = capture(device, limit, cancelled);
  struct stat after{};
  if (result.outcome == CaptureOutcome::Success && (!regular(fd, after) || !same(identity, after)))
    return {CaptureOutcome::IoFailure, {}};
  return result;
}
}  // namespace
bool validResourcePaths(const QStringList& paths) {
  if (paths.size() > 256) return false;
  QJsonArray json;
  QSet<QString> unique;
  for (const auto& path : paths) {
    if (!validPath(path) || path == "main.svg" || path.startsWith("main.svg/")) return false;
    unique.insert(path);
    json.append(path);
  }
  if (QJsonDocument(QJsonObject{{"paths", json}}).toJson(QJsonDocument::Compact).size() > 65536) return false;
  for (const auto& path : unique) {
    auto parent = path;
    while (parent.contains('/')) {
      parent = parent.left(parent.lastIndexOf('/'));
      if (unique.contains(parent)) return false;
    }
  }
  return true;
}
LinkedAcquisition::LinkedAcquisition(int base, int main, QString mainName)
    : base_(fcntl(base, F_DUPFD_CLOEXEC, 3)), main_(fcntl(main, F_DUPFD_CLOEXEC, 3)), mainName_(std::move(mainName)) {}
LinkedAcquisition::~LinkedAcquisition() {
  if (base_ >= 0) close(base_);
  if (main_ >= 0) close(main_);
}
CaptureResult LinkedAcquisition::captureMain(const std::atomic_bool& cancelled) {
  ready_ = false;
  mainBytes_.clear();
  published_.clear();
  identities_.clear();
  if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
  struct stat base{};
  if (base_ < 0 || main_ < 0 || fstat(base_, &base) || !S_ISDIR(base.st_mode) || !validPath(mainName_))
    return {CaptureOutcome::IoFailure, {}};
  auto result = readFile(main_, 10 * 1024 * 1024, cancelled, mainIdentity_);
  if (result.outcome != CaptureOutcome::Success) return result;
  if (!revalidate(base_, mainName_, mainIdentity_)) return {CaptureOutcome::IoFailure, {}};
  if (cancelled.load()) return {CaptureOutcome::Cancelled, {}};
  mainBytes_ = result.bytes;
  ready_ = true;
  return result;
}
CaptureOutcome LinkedAcquisition::complete(const QStringList& paths, const std::atomic_bool& cancelled,
                                           const std::function<void()>& beforeRevalidation) {
  published_.clear();
  identities_.clear();
  if (cancelled.load()) return CaptureOutcome::Cancelled;
  if (!ready_) return CaptureOutcome::IoFailure;
  ready_ = false;
  if (!validResourcePaths(paths)) return CaptureOutcome::ResourceLimit;
  QMap<QString, QByteArray> pending{{"main.svg", mainBytes_}};
  QMap<QString, struct stat> records;
  qint64 total = mainBytes_.size();
  for (const auto& path : paths) {
    if (cancelled.load()) return CaptureOutcome::Cancelled;
    if (records.contains(path)) continue;
    if (total == inputCeiling) return CaptureOutcome::ResourceLimit;
    const int fd = openBeneath(base_, path);
    if (fd < 0) return CaptureOutcome::IoFailure;
    struct stat identity{};
    auto result = readFile(fd, inputCeiling - total, cancelled, identity);
    close(fd);
    if (result.outcome != CaptureOutcome::Success) return result.outcome;
    total += result.bytes.size();
    pending.insert(path, std::move(result.bytes));
    records.insert(path, identity);
  }
  if (beforeRevalidation) beforeRevalidation();
  if (cancelled.load()) return CaptureOutcome::Cancelled;
  for (auto it = records.cbegin(); it != records.cend(); ++it) {
    if (cancelled.load()) return CaptureOutcome::Cancelled;
    if (!revalidate(base_, it.key(), it.value())) return CaptureOutcome::IoFailure;
  }
  struct stat currentMain{};
  if (!regular(main_, currentMain) || !same(mainIdentity_, currentMain) || !revalidate(base_, mainName_, mainIdentity_))
    return CaptureOutcome::IoFailure;
  if (cancelled.load()) return CaptureOutcome::Cancelled;
  records.insert("main.svg", mainIdentity_);
  identities_ = std::move(records);
  published_ = std::move(pending);
  return CaptureOutcome::Success;
}
}  // namespace Comparison
