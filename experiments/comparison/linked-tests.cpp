// SPDX-License-Identifier: GPL-3.0-or-later
#include "linked-acquisition.h"

#include <QCoreApplication>
#include <QDir>
#include <QTemporaryDir>

#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

using namespace Comparison;
namespace {
int failures = 0;
void check(bool ok, const char* name) {
  std::printf("%s: %s\n", ok ? "PASS" : "FAIL", name);
  if (!ok) ++failures;
}
void write(const QString& path, const QByteArray& bytes) {
  QFile file(path);
  if (!file.open(QIODevice::WriteOnly | QIODevice::Truncate) || file.write(bytes) != bytes.size()) std::abort();
}
}  // namespace
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  QTemporaryDir temporary;
  const auto root = temporary.path();
  QDir().mkdir(root + "/base");
  auto basePath = root + "/base";
  write(basePath + "/source.svg", "main");
  write(basePath + "/pixel.png", "pixel");
  const int base = open(basePath.toUtf8().constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  const int main = open((basePath + "/source.svg").toUtf8().constData(), O_RDONLY | O_CLOEXEC);
  std::atomic_bool cancelled{false};
  auto run = [&](const QStringList& paths, const std::function<void()>& barrier = {}) {
    LinkedAcquisition acquisition(base, main, "source.svg");
    check(acquisition.captureMain(cancelled).outcome == CaptureOutcome::Success, "capture main");
    const auto result = acquisition.complete(paths, cancelled, barrier);
    if (result != CaptureOutcome::Success) check(acquisition.files().isEmpty(), "no partial publication");
    return result;
  };
  check(run({"pixel.png", "pixel.png"}) == CaptureOutcome::Success, "deduplicate references");
  check(fcntl(base, F_GETFD) >= 0 && fcntl(main, F_GETFD) >= 0, "caller descriptor ownership");
  for (const auto& path : {"../pixel.png", "/pixel.png", "a//b", "a/./b", "a%20b", "a?b", "a#b", "main.svg",
                           "main.svg/x", "https:x", "a\\b"})
    check(run({path}) == CaptureOutcome::ResourceLimit, "invalid paths/collisions");
  check(!validResourcePaths({"a", "a-", "a/b"}), "nonadjacent prefix collision");
  check(!validResourcePaths({QString(1025, 'a')}), "path byte limit");
  check(validResourcePaths({QString(512, QChar(0xe9))}), "UTF-8 path boundary accepted");
  check(!validResourcePaths({QString(513, QChar(0xe9))}), "UTF-8 byte limit enforced");
  check(validResourcePaths(QStringList(256, "pixel.png")), "occurrence boundary accepted");
  LinkedAcquisition mismatch(base, main, "pixel.png");
  check(mismatch.captureMain(cancelled).outcome == CaptureOutcome::IoFailure, "main descriptor/name mismatch");
  symlink("source.svg", (basePath + "/main-alias").toUtf8().constData());
  LinkedAcquisition mainSymlink(base, main, "main-alias");
  check(mainSymlink.captureMain(cancelled).outcome == CaptureOutcome::IoFailure, "main symlink rejected");
  check(!validResourcePaths(QStringList(257, "pixel.png")), "occurrence limit");
  QStringList large;
  for (int i = 0; i < 256; ++i) large.append(QString::number(i) + QString(1000, 'a'));
  check(!validResourcePaths(large), "control record limit");
  check(run({"missing"}) == CaptureOutcome::IoFailure, "missing file");
  QDir().mkdir(basePath + "/dir");
  check(run({"dir"}) == CaptureOutcome::IoFailure, "directory rejected");
  symlink("pixel.png", (basePath + "/link").toUtf8().constData());
  check(run({"link"}) == CaptureOutcome::IoFailure, "final symlink rejected");
  symlink("dir", (basePath + "/alias").toUtf8().constData());
  check(run({"alias/file"}) == CaptureOutcome::IoFailure, "intermediate symlink rejected");
  mkfifo((basePath + "/fifo").toUtf8().constData(), 0600);
  check(run({"fifo"}) == CaptureOutcome::IoFailure, "FIFO rejected without blocking");
  const int sock = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  const auto socketPath = (basePath + "/socket").toUtf8();
  std::strncpy(address.sun_path, socketPath.constData(), sizeof(address.sun_path) - 1);
  check(bind(sock, reinterpret_cast<sockaddr*>(&address), sizeof address) == 0, "socket fixture");
  check(run({"socket"}) == CaptureOutcome::IoFailure, "socket rejected");
  close(sock);
  const int nullDevice = open("/dev/null", O_RDONLY | O_CLOEXEC);
  LinkedAcquisition device(base, nullDevice, "source.svg");
  check(device.captureMain(cancelled).outcome == CaptureOutcome::IoFailure, "device rejected");
  close(nullDevice);
  // A sparse file exercises the actual aggregate count, including main bytes.
  QFile huge(basePath + "/huge");
  check(huge.open(QIODevice::WriteOnly) && huge.resize(inputCeiling), "aggregate fixture");
  huge.close();
  check(run({"huge"}) == CaptureOutcome::ResourceLimit, "aggregate captured byte limit");
  QFile::remove(basePath + "/huge");
  write(basePath + "/unreadable", "unreferenced");
  QFile::setPermissions(basePath + "/unreadable", {});
  check(run({"pixel.png"}) == CaptureOutcome::Success, "unrelated unreadable file ignored");
  const int filesystemRoot = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  const int procMain = open("/proc/version", O_RDONLY | O_CLOEXEC);
  LinkedAcquisition mount(filesystemRoot, procMain, "proc/version");
  check(mount.captureMain(cancelled).outcome == CaptureOutcome::IoFailure, "mount crossing rejected");
  close(procMain);
  close(filesystemRoot);
  check(run({"pixel.png"}, [&] { write(basePath + "/pixel.png", "other"); }) == CaptureOutcome::IoFailure,
        "barrier: mutation detected");
  check(run({"pixel.png"},
            [&] {
              QFile::rename(basePath + "/pixel.png", basePath + "/old");
              write(basePath + "/pixel.png", "other");
            }) == CaptureOutcome::IoFailure,
        "barrier: final replacement detected");
  write(basePath + "/dir/child", "child");
  check(run({"dir/child"},
            [&] {
              QDir().rename(basePath + "/dir", basePath + "/old-dir");
              QDir().mkdir(basePath + "/dir");
              write(basePath + "/dir/child", "child");
            }) == CaptureOutcome::IoFailure,
        "barrier: directory replacement detected");
  check(run({"pixel.png"}, [&] { QFile::remove(basePath + "/pixel.png"); }) == CaptureOutcome::IoFailure,
        "barrier: deletion detected");
  write(basePath + "/pixel.png", "pixel");
  check(run({"pixel.png"}, [&] { cancelled.store(true); }) == CaptureOutcome::Cancelled,
        "barrier: cancellation before publication");
  cancelled.store(false);
  check(run({"pixel.png"},
            [&] {
              QDir().rename(basePath, root + "/pinned");
              QDir().mkdir(basePath);
              write(basePath + "/source.svg", "replacement");
              write(basePath + "/pixel.png", "replacement");
              basePath = root + "/pinned";
            }) == CaptureOutcome::Success,
        "barrier: pinned base rename and replacement");
  check(run({}, [&] { write(basePath + "/source.svg", "mutation"); }) == CaptureOutcome::IoFailure,
        "barrier: main mutation detected");
  check(run({},
            [&] {
              QFile::rename(basePath + "/source.svg", basePath + "/old-main");
              write(basePath + "/source.svg", "mutation");
            }) == CaptureOutcome::IoFailure,
        "barrier: main replacement detected");
  QFile::remove(basePath + "/source.svg");
  QFile::rename(basePath + "/old-main", basePath + "/source.svg");
  cancelled.store(true);
  LinkedAcquisition cancelledInput(base, main, "source.svg");
  check(cancelledInput.captureMain(cancelled).outcome == CaptureOutcome::Cancelled, "pre-capture cancellation");
  cancelled.store(false);
  write(basePath + "/source.svg", QByteArray(10 * 1024 * 1024 + 1, 'x'));
  LinkedAcquisition oversized(base, main, "source.svg");
  check(oversized.captureMain(cancelled).outcome == CaptureOutcome::ResourceLimit, "main SVG byte limit");
  close(main);
  close(base);
  return failures ? 1 : 0;
}
