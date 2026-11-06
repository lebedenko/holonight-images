// SPDX-License-Identifier: GPL-3.0-or-later
#include "source-capture.h"

#include <QCoreApplication>
#include <QFile>

#include <cstdio>

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  if (argc != 3) {
    std::fprintf(stderr, "usage: capture-probe PATH BYTE_LIMIT\n");
    return 1;
  }
  bool valid = false;
  const auto limit = QString::fromLocal8Bit(argv[2]).toLongLong(&valid);
  QFile source(QString::fromLocal8Bit(argv[1]));
  if (!valid || !source.open(QIODevice::ReadOnly)) {
    std::fprintf(stderr, "invalid limit or source open failure\n");
    return 1;
  }
  const std::atomic_bool cancelled{false};
  const auto result = Comparison::capture(source, limit, cancelled);
  const char* names[] = {"Success", "IoFailure", "ResourceLimit", "Cancelled"};
  std::fprintf(stderr, "%s: %lld bytes\n", names[int(result.outcome)], static_cast<long long>(result.bytes.size()));
  if (result.outcome != Comparison::CaptureOutcome::Success) return 1;
  if (std::fwrite(result.bytes.constData(), 1, size_t(result.bytes.size()), stdout) != size_t(result.bytes.size()))
    return 1;
  return std::fflush(stdout) == 0 ? 0 : 1;
}
