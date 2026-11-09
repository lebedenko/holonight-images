// SPDX-License-Identifier: GPL-3.0-or-later
#include <QBuffer>
#include <QCoreApplication>
#include <QDir>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QTemporaryDir>
#include <QThread>

#include <atomic>
#include <cstdio>
#include <holonight_images/isolated.h>
#include <print>
#include <stdexcept>
#include <sys/stat.h>
#include <thread>
using namespace HolonightImages;
namespace {
const Limits limits{.inputBytes = 1048576,
                    .sourcePixels = 100000,
                    .sourceExtent = 1000,
                    .decodedBytes = 1048576,
                    .metadataBytes = 1024,
                    .tiffMetadataBytes = 1024,
                    .metadataRecords = 100};
void require(bool value, const char* message) {
  if (!value) {
    throw std::runtime_error(message);
  }
}
QByteArray read(const QString& path) {
  QFile file(path);
  if (!file.open(QIODevice::ReadOnly)) {
    return {};
  }
  return file.readAll();
}
QString readyScope() {
  for (const auto& pid : QDir("/proc").entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
    if (read("/proc/" + pid + "/comm").trimmed() != "hn-test-ready") {
      continue;
    }
    for (const auto& line : read("/proc/" + pid + "/cgroup").split('\n')) {
      if (line.startsWith("0::") && line.contains("holonight-images-")) {
        return "/sys/fs/cgroup" + QString::fromUtf8(line.mid(3));
      }
    }
  }
  return {};
}
bool empty(const QString& group) {
  return !QFileInfo::exists(group) || read(group + "/cgroup.events").split('\n').contains("populated 0");
}
QByteArray boundaryPayload(qsizetype size) {
  QByteArray payload(size, '\0');
  payload.replace(0, 8, "payload:");
  for (qsizetype i = 8; i < payload.size(); ++i) {
    payload[i] = static_cast<char>(i % 251);
  }
  return payload;
}
}  // namespace
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  const auto arguments = QCoreApplication::arguments();
  try {
    require(argc == 3, "good and fault runtimes required");
    IsolatedClient good(arguments[1]);
    IsolatedClient fault(arguments[2]);
    std::atomic_bool cancelled{false};
    auto request = [&](const IsolatedClient& client, QByteArray bytes) {
      QBuffer source(&bytes);
      source.open(QIODevice::ReadOnly);
      auto result = client.decode(source, {.limits = limits, .bound = {}}, cancelled);
      require(source.isOpen(), "caller closed");
      return result;
    };
    if (qEnvironmentVariableIsSet("HN_TEST_NAMESPACE_DENIED")) {
      auto denied = request(good, "x");
      require(denied.runtime == RuntimeStatus::Unavailable && !denied.result, "namespace denial did not fail closed");
      return 0;
    }
    for (const auto size : {65536, 131072, 131089}) {
      const auto result = request(fault, boundaryPayload(size));
      require(
          result.runtime == RuntimeStatus::Success && result.result && result.result->outcome == Outcome::Unsupported,
          "chunk-boundary payload changed or protocol did not complete");
    }
    for (const auto* mode : {"crash", "malformed", "partial"}) {
      const auto result = request(fault, mode);
      require(result.runtime == RuntimeStatus::ProtocolFailure && !result.result,
              "fault produced partial result or wrong status");
    }
    const auto hang = request(fault, "hang");
    require(hang.runtime == RuntimeStatus::Timeout && !hang.result, "hang not timed out and cleaned");
    require(hang.elapsedMilliseconds >= 15000 && hang.elapsedMilliseconds < 20500, "timeout/cleanup budget");
    QByteArray backpressure(1048576, 'x');
    backpressure.replace(0, 12, "backpressure");
    for (const auto& mode :
         {QByteArray("descendant"), QByteArray("race"), QByteArray("race"), QByteArray("race"), backpressure}) {
      cancelled = false;
      std::atomic_bool done{false};
      QString group;
      std::jthread cancel([&] {
        QElapsedTimer clock;
        clock.start();
        while (!done.load() && clock.elapsed() < 10000) {
          group = readyScope();
          if (!group.isEmpty()) {
            cancelled = true;
            return;
          }
          QThread::msleep(1);
        }
      });
      auto result = request(fault, mode);
      done = true;
      cancel.join();
      require(!group.isEmpty(), "helper readiness not observed");
      require(result.runtime == RuntimeStatus::Cancelled && !result.result, "cancel reply retained or cleanup failed");
      require(empty(group), "descendant scope not empty");
      require(result.elapsedMilliseconds < 6000, "cancellation cleanup budget");
    }
    cancelled = true;
    require(request(good, "unused").runtime == RuntimeStatus::Cancelled, "pre-cancellation");
    cancelled = false;
    auto missing = request(IsolatedClient("/nonexistent/holonight-runtime"), "x");
    require(missing.runtime == RuntimeStatus::Unavailable && !missing.result, "missing runtime not unavailable");
    {
      QTemporaryDir temporary;
      require(temporary.isValid(), "temporary runtime directory");
      const QString& original = arguments[1];
      QDirIterator files(original, QDir::Files, QDirIterator::Subdirectories);
      while (files.hasNext()) {
        const auto from = files.next();
        const auto target = temporary.path() + "/" + QDir(original).relativeFilePath(from);
        require(QDir().mkpath(QFileInfo(target).path()) && QFile::copy(from, target), "runtime copy");
      }
      IsolatedClient altered(temporary.path());
      const auto plugin = temporary.path() + "/usr/lib/qt6/plugins/imageformats/libqjpeg.so";
      auto unavailable = [&] {
        auto result = request(altered, "x");
        require(result.runtime == RuntimeStatus::Unavailable && !result.result, "altered runtime accepted");
      };
      require(QFile::rename(plugin, temporary.path() + "/missing"), "rename fixture");
      unavailable();
      require(QFile::rename(temporary.path() + "/missing", plugin), "restore fixture");
      require(chmod(QFile::encodeName(plugin).constData(), 04755) == 0, "set special mode fixture");
      unavailable();
      require(chmod(QFile::encodeName(plugin).constData(), 0755) == 0, "restore fixture mode");
      const auto contents = read(plugin);
      QFile corrupt(plugin);
      require(corrupt.open(QIODevice::WriteOnly), "alter plugin");
      require(corrupt.write("altered") == 7, "write alteration");
      corrupt.close();
      unavailable();
      require(corrupt.open(QIODevice::WriteOnly), "restore plugin");
      require(corrupt.write(contents) == contents.size(), "restore bytes");
      corrupt.close();
      QFile extra(temporary.path() + "/unexpected");
      require(extra.open(QIODevice::WriteOnly), "extra fixture");
      extra.close();
      unavailable();
    }
    // Recovery uses independent known PNG bytes, not a decoder-generated oracle.
    const auto png = QByteArray::fromBase64(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DQAAAEgQGALFXOsAAAAABJRU5ErkJggg==");
    qputenv("QT_PLUGIN_PATH", "/nonexistent/poison");
    qputenv("LD_LIBRARY_PATH", "/nonexistent/poison");
    qputenv("LD_PRELOAD", "/nonexistent/poison.so");
    qputenv("PATH", "/nonexistent/poison");
    qputenv("QT_IMAGEIO_MAXALLOC", "1");
    auto recovery = request(good, png);
    require(
        recovery.runtime == RuntimeStatus::Success && recovery.result && recovery.result->outcome == Outcome::Success,
        "poisoned environment recovery failed");
    require(recovery.result->image.pixelColor(0, 0) == QColor(255, 0, 0, 128), "independent recovery pixel");
    std::puts("runtime faults, timeout, cancellation races, descendant cleanup and poisoned recovery passed");
    return 0;
  } catch (const std::exception& e) {
    std::println(stderr, "{}", e.what());
    return 1;
  }
}
