// SPDX-License-Identifier: GPL-3.0-or-later
#include "source-capture.h"

#include <QBuffer>

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <functional>
#include <stdexcept>

using namespace Comparison;
namespace {
void require(bool ok, const char* message) {
  if (!ok) throw std::runtime_error(message);
}
class Device : public QIODevice {
 public:
  QByteArray data = "abcdef";
  qint64 offset = 0;
  qint64 reportedSize = 0;
  qint64 shortRead = 65536;
  int reads = 0;
  int seeks = 0;
  int failRead = -1;
  bool sequential = false;
  bool failSeek = false;
  std::function<void()> onSeek;
  std::function<void(int)> onRead;
  Device() { open(ReadOnly | Unbuffered); }
  bool isSequential() const override { return sequential; }
  qint64 size() const override { return reportedSize; }
  bool atEnd() const override { return true; }
  bool seek(qint64 position) override {
    ++seeks;
    if (onSeek) onSeek();
    if (failSeek) return false;
    offset = position;
    return QIODevice::seek(position);
  }

 protected:
  qint64 readData(char* output, qint64 maximum) override {
    require(maximum <= 65536, "oversized read");
    ++reads;
    if (onRead) onRead(reads);
    if (reads == failRead) return -1;
    auto count = std::min({maximum, shortRead, std::max<qint64>(0, data.size() - offset)});
    std::memcpy(output, data.constData() + offset, size_t(count));
    offset += count;
    return count;
  }
  qint64 writeData(const char*, qint64) override { return -1; }
};
void expect(Device& device, qint64 limit, CaptureOutcome outcome, const QByteArray& bytes = {}) {
  const std::atomic_bool cancelled{false};
  auto result = capture(device, limit, cancelled);
  require(result.outcome == outcome, "unexpected outcome");
  require(result.bytes == bytes, "payload mismatch or partial failure payload");
  require(device.isOpen(), "capture closed caller device");
}
}  // namespace
int main() {
  try {
    std::atomic_bool cancelled{false};
    QBuffer buffer;
    buffer.setData("owned");
    buffer.open(QIODevice::ReadOnly);
    buffer.seek(3);
    auto owned = capture(buffer, 5, cancelled);
    require(buffer.isOpen(), "capture closed caller buffer");
    buffer.close();
    buffer.setData("replaced");
    require(owned.outcome == CaptureOutcome::Success && owned.bytes == "owned", "caller ownership/offset");
    for (qint64 length : {0, 1, 65535, 65536, 65537, 131072}) {
      for (qint64 delta : {-1, 0, 1}) {
        Device device;
        device.data = QByteArray(length, 'x');
        const qint64 limit = std::max<qint64>(1, length + delta);
        expect(device, limit, length > limit ? CaptureOutcome::ResourceLimit : CaptureOutcome::Success,
               length > limit ? QByteArray{} : device.data);
        require(device.offset <= limit + 1, "read beyond overflow probe");
      }
    }
    {
      Device device;
      expect(device, inputCeiling, CaptureOutcome::Success, "abcdef");
    }
    for (qint64 limit : {-1LL, 0LL, inputCeiling + 1}) {
      Device device;
      expect(device, limit, CaptureOutcome::ResourceLimit);
      require(device.seeks == 0 && device.reads == 0, "invalid limit performed IO");
    }
    for (int kind = 0; kind < 4; ++kind) {
      Device device;
      if (kind == 0) device.close();
      if (kind == 1) {
        device.close();
        device.open(QIODevice::WriteOnly | QIODevice::Unbuffered);
      }
      if (kind == 2) device.sequential = true;
      if (kind == 3) device.failSeek = true;
      auto result = capture(device, 10, cancelled);
      require(result.outcome == CaptureOutcome::IoFailure && result.bytes.isEmpty(), "invalid device");
      require(device.reads == 0, "invalid device read");
    }
    for (int failure : {1, 2}) {
      Device device;
      device.shortRead = 2;
      device.failRead = failure;
      expect(device, 10, CaptureOutcome::IoFailure);
    }
    for (qint64 size : {0, 999999}) {
      Device device;
      device.reportedSize = size;
      device.shortRead = 1;
      expect(device, 6, CaptureOutcome::Success, "abcdef");
    }
    for (bool overflow : {false, true}) {
      Device device;
      device.shortRead = 2;
      device.onRead = [&](int n) {
        if (n == 2) device.data.append("ghi");
      };
      expect(device, overflow ? 6 : 10, overflow ? CaptureOutcome::ResourceLimit : CaptureOutcome::Success,
             overflow ? QByteArray{} : QByteArray("abcdefghi"));
    }
    {
      Device device;
      device.shortRead = 2;
      device.onRead = [&](int n) {
        if (n == 2) device.data.truncate(3);
      };
      expect(device, 10, CaptureOutcome::Success, "abc");
    }
    // Before IO, during seek, during data read, EOF read and overflow probe.
    for (int point : {0, 1, 2, 3, 4}) {
      Device device;
      if (point == 4) device.data.append("g");
      cancelled = point == 0;
      if (point == 1) device.onSeek = [&] { cancelled = true; };
      device.onRead = [&](int n) {
        if ((point == 2 && n == 1) || ((point == 3 || point == 4) && n == 2)) cancelled = true;
      };
      const auto result = capture(device, point == 4 ? 6 : 10, cancelled);
      require(result.outcome == CaptureOutcome::Cancelled && result.bytes.isEmpty(), "cancel payload/outcome");
      require(device.seeks == (point == 0 ? 0 : 1), "operations after initial cancellation");
      require(device.reads == (point <= 1 ? 0 : point == 2 ? 1 : 2), "operations after callback cancellation");
    }
    std::puts("source capture contract passed");
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
  }
}
