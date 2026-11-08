// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime.h"

#include <QCryptographicHash>
#include <QDeadlineTimer>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QProcess>
#include <QSet>
#include <QThread>
#include <QUuid>
#include <QtEndian>

#include <span>
#include <sys/stat.h>
#include <utility>

namespace HolonightImages::Isolation {
namespace {
struct Failure {
  RuntimeStatus status;
  QString message;
};
QByteArray fileBytes(const QString& path, qint64 limit = controlCeiling) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) {
    return {};
  }
  auto bytes = file.read(limit + 1);
  return bytes.size() <= limit ? bytes : QByteArray{};
}
QProcessEnvironment environment() {
  QProcessEnvironment env;
  env.insert("PATH", "/usr/bin");
  env.insert("LANG", "C");
  env.insert("LC_ALL", "C");
  for (const auto* key : {"XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"}) {
    if (qEnvironmentVariableIsSet(key)) {
      env.insert(key, qEnvironmentVariable(key));
    }
  }
  return env;
}
// Keep the ordered security/lifecycle checks together for auditing.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
QStringList validate(const QString& root) {
  if (!QDir::isAbsolutePath(root) || QFileInfo(root).isSymLink()) {
    throw Failure{.status = RuntimeStatus::Unavailable, .message = "runtime must be an explicit absolute directory"};
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
QString groupOf(qint64 pid, const QString& unit) {
  for (const auto& line : fileBytes(QString("/proc/%1/cgroup").arg(pid)).split('\n')) {
    if (line.startsWith("0::") && line.endsWith(unit.toUtf8())) {
      const auto path = QString::fromUtf8(line.mid(3));
      if (path.startsWith('/') && QDir::cleanPath(path) == path) {
        return "/sys/fs/cgroup" + path;
      }
    }
  }
  return {};
}
bool empty(const QString& group) {
  if (group.isEmpty()) {
    return false;
  }
  if (!QFileInfo::exists(group)) {
    return true;
  }
  return fileBytes(group + "/cgroup.events").split('\n').contains("populated 0");
}
QString manager(const QStringList& args, QDeadlineTimer& deadline) {
  QProcess process;
  process.setProcessEnvironment(environment());
  process.start("/usr/bin/systemctl", QStringList{"--user"} + args);
  if (!process.waitForFinished(static_cast<int>(qMax<qint64>(1, deadline.remainingTime())))) {
    process.kill();
    process.waitForFinished(1);
    throw ProtocolError("scope manager deadline");
  }
  if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
    throw ProtocolError("scope manager failed");
  }
  return QString::fromUtf8(process.readAllStandardOutput()).trimmed();
}
// Keep the ordered security/lifecycle checks together for auditing.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
bool cleanup(QProcess& process, const QString& unit, QString& group) {
  QDeadlineTimer deadline(5000);
  try {
    if (group.isEmpty()) {
      auto path = manager({"show", "--property=ControlGroup", "--value", unit}, deadline);
      if (!path.isEmpty() && path.startsWith('/') && QDir::cleanPath(path) == path && path.endsWith('/' + unit)) {
        {
          group = "/sys/fs/cgroup" + path;
        }
      } else {
        process.waitForFinished(50);
        if (process.state() == QProcess::NotRunning &&
            manager({"show", "--property=LoadState", "--value", unit}, deadline) == "not-found") {
          return true;
        }
        throw ProtocolError("scope identity unavailable");
      }
    }
    if (!empty(group)) {
      try {
        manager({"kill", "--signal=TERM", unit}, deadline);
      } catch (...) {
        if (!empty(group)) {
          throw;
        }
      }
      QElapsedTimer grace;
      grace.start();
      while (!empty(group) && grace.elapsed() < 1000 && !deadline.hasExpired()) {
        QThread::msleep(5);
      }
      if (!empty(group)) {
        try {
          manager({"kill", "--signal=KILL", unit}, deadline);
        } catch (...) {
          if (!empty(group)) {
            throw;
          }
        }
      }
    }
    while (!empty(group) && !deadline.hasExpired()) {
      QThread::msleep(5);
    }
    if (process.state() != QProcess::NotRunning) {
      process.waitForFinished(static_cast<int>(qMax<qint64>(1, deadline.remainingTime())));
    }
    if (!deadline.hasExpired() && empty(group) && process.state() == QProcess::NotRunning) {
      return true;
    }
  } catch (...) {
  }
  process.kill();
  process.waitForFinished(static_cast<int>(qMax<qint64>(1, deadline.remainingTime())));
  return false;
}
}  // namespace
void verifyRuntime(const QString& directory) { validate(directory); }

// Keep the ordered security/lifecycle checks together for auditing.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
TransportResult dispatch(const QString& runtime, const Request& request, const QByteArray& input,
                         const std::atomic_bool& cancelled) {
  TransportResult result;
  QElapsedTimer elapsed;
  elapsed.start();
  QProcess process;
  QString group;
  QString unit;
  bool launched = false;
  try {
    QStringList binds;
    try {
      binds = validate(runtime);
    } catch (const std::exception& e) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = QString::fromUtf8(e.what())};
    }
    if (cancelled.load()) {
      throw Failure{.status = RuntimeStatus::Cancelled, .message = "cancelled before launch"};
    }
    for (const auto* tool : {"/usr/bin/bwrap", "/usr/bin/systemd-run", "/usr/bin/systemctl"}) {
      if (!QFileInfo(tool).isExecutable()) {
        throw Failure{.status = RuntimeStatus::Unavailable, .message = "missing runtime launcher"};
      }
    }
    unit = "holonight-images-" + QUuid::createUuid().toString(QUuid::Id128) + ".scope";
    QStringList sandbox{"/usr/bin/bwrap",
                        "--unshare-all",
                        "--die-with-parent",
                        "--new-session",
                        "--clearenv",
                        "--setenv",
                        "PATH",
                        "/usr/bin",
                        "--setenv",
                        "HOME",
                        "/tmp",
                        "--setenv",
                        "QT_PLUGIN_PATH",
                        "/usr/lib/qt6/plugins",
                        "--setenv",
                        "QT_IMAGEIO_MAXALLOC",
                        "256",
                        "--proc",
                        "/proc",
                        "--dev",
                        "/dev",
                        "--tmpfs",
                        "/tmp",
                        "--dir",
                        "/run",
                        "--dir",
                        "/usr/lib",
                        "--symlink",
                        "usr/lib",
                        "/lib",
                        "--symlink",
                        "usr/lib",
                        "/lib64"};
    sandbox += binds;
    sandbox << "--remount-ro" << "/" << "--" << "/usr/libexec/holonight-images-helper";
    QStringList command{"--user",
                        "--scope",
                        "--quiet",
                        "--unit=" + unit,
                        "--property=MemoryMax=2G",
                        "--property=MemorySwapMax=0",
                        runtime + "/usr/libexec/holonight-images-helper",
                        "--gate"};
    command += sandbox;
    process.setUnixProcessParameters(
        {.flags = QProcess::UnixProcessFlag::CloseFileDescriptors | QProcess::UnixProcessFlag::CreateNewSession,
         .lowestFileDescriptorToClose = 3});
    process.setProcessEnvironment(environment());
    process.setStandardErrorFile(QProcess::nullDevice());
    process.start("/usr/bin/systemd-run", command);
    if (!process.waitForStarted(1000)) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "launcher failed to start"};
    }
    launched = true;
    QDeadlineTimer deadline(15000);
    auto check = [&] {
      if (cancelled.load()) {
        throw Failure{.status = RuntimeStatus::Cancelled, .message = "cancelled"};
      }
      if (process.bytesAvailable() > byteCeiling + controlCeiling + 4) {
        throw ProtocolError("oversized helper response");
      }
      if (deadline.hasExpired()) {
        throw Failure{.status = RuntimeStatus::Timeout, .message = "15 second request deadline"};
      }
      if (!group.isEmpty()) {
        bool parsed = false;
        const auto memory = fileBytes(group + "/memory.peak").trimmed().toLongLong(&parsed);
        if (parsed) {
          result.peak_memory = qMax(result.peak_memory, memory);
        }
      }
    };
    while (group.isEmpty()) {
      check();
      group = groupOf(process.processId(), unit);
      if (process.state() == QProcess::NotRunning) {
        throw Failure{.status = RuntimeStatus::Unavailable, .message = "scope startup failed"};
      }
      if (group.isEmpty()) {
        process.waitForFinished(5);
      }
    }
    if (fileBytes(group + "/memory.max").trimmed() != "2147483648" ||
        fileBytes(group + "/memory.swap.max").trimmed() != "0") {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "scope limits not enforced"};
    }
    auto receive = [&](qint64 size) {
      QByteArray bytes;
      while (bytes.size() < size) {
        check();
        if (process.bytesAvailable() > byteCeiling + controlCeiling + 4) {
          throw ProtocolError("oversized helper response");
        }
        auto part = process.read(qMin<qint64>(65536, size - bytes.size()));
        bytes += part;
        if (bytes.size() == size) {
          break;
        }
        if (process.state() == QProcess::NotRunning && !process.bytesAvailable()) {
          throw ProtocolError("helper EOF");
        }
        process.waitForReadyRead(5);
      }
      return bytes;
    };
    if (process.write("G", 1) != 1) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "launcher gate write failed"};
    }
    process.waitForBytesWritten(5);
    try {
      if (receive(1) != "R") {
        throw ProtocolError("missing helper readiness");
      }
    } catch (const ProtocolError&) {
      throw Failure{.status = RuntimeStatus::Unavailable, .message = "sandbox helper failed before readiness"};
    }
    result.startup = elapsed.elapsed();
    QByteArray outgoing = frame(requestControl(request, input.size()));
    outgoing += input;
    qint64 sent = 0;
    while (sent < outgoing.size() || (process.bytesToWrite() != 0)) {
      check();
      if (sent < outgoing.size() && process.bytesToWrite() < 65536) {
        const auto written = process.write(std::span<const char>(outgoing).subspan(sent).data(),
                                           qMin<qint64>(65536, outgoing.size() - sent));
        if (written < 0) {
          throw ProtocolError("helper write failed");
        }
        sent += written;
      }
      process.waitForBytesWritten(5);
      if (process.state() == QProcess::NotRunning) {
        throw ProtocolError("helper exited during request");
      }
    }
    const auto length = qFromBigEndian<quint32>(receive(4).constData());
    if ((length == 0U) || length > controlCeiling) {
      throw ProtocolError("response control limit");
    }
    const auto control = parseControl(receive(length));
    const auto bytes = integer(control, "bytes", 0, qMin(byteCeiling, request.options.limits.decodedBytes));
    const auto pixels = receive(bytes);
    auto reply = parseReply(control, pixels, request);
    check();  // Sample the final peak while the helper is still waiting for acknowledgement.
    result.operation = elapsed.elapsed() - result.startup;
    if (process.write("A", 1) != 1) {
      throw ProtocolError("helper acknowledgement failed");
    }
    process.closeWriteChannel();
    while (process.state() != QProcess::NotRunning) {
      check();
      if (process.bytesAvailable() != 0) {
        throw ProtocolError("trailing response");
      }
      process.waitForFinished(5);
    }
    if ((process.bytesAvailable() != 0) || process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
      throw ProtocolError("helper failed or trailing response");
    }
    check();
    result.reply = std::move(reply);
    result.status = RuntimeStatus::Success;
  } catch (const Failure& e) {
    result.status = e.status;
    result.diagnostic = e.message;
  } catch (const std::exception& e) {
    result.status = RuntimeStatus::ProtocolFailure;
    result.diagnostic = QString::fromUtf8(e.what());
  }
  if (cancelled.load()) {
    result.status = RuntimeStatus::Cancelled;
    result.reply.reset();
  }
  if (launched && !cleanup(process, unit, group)) {
    result.status = RuntimeStatus::CleanupFailure;
    result.diagnostic = "hierarchical cleanup or launcher reaping unverified";
  }
  if (cancelled.load() && result.status != RuntimeStatus::CleanupFailure) {
    result.status = RuntimeStatus::Cancelled;
  }
  if (result.status != RuntimeStatus::Success) {
    result.reply.reset();
  }
  result.elapsed = elapsed.elapsed();
  return result;
}
}  // namespace HolonightImages::Isolation
