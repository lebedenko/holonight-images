// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "fault-control.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonObject>
#include <QProcess>

#include <array>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <signal.h>
#include <stdexcept>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

namespace Profile {
inline constexpr bool detailed = PROFILE_DETAILED;
inline constexpr size_t recordLimit = 32768;
inline constexpr qsizetype byteLimit = 256 * 1024;
inline qint64 now() {
  timespec value{};
  if (clock_gettime(CLOCK_MONOTONIC, &value)) throw std::runtime_error("monotonic clock");
  return value.tv_sec * 1000000000LL + value.tv_nsec;
}
struct Event {
  const char* mark;
  qint64 ns;
  qint64 value;
};
inline std::array<Event, recordLimit> ledger;
inline size_t used = 0;
inline bool failed = false;
inline QByteArray errors;
inline QString fault, journal, cleanupJson;
inline std::atomic_bool* cancellation = nullptr;
inline bool qualification = false;
inline bool awaiting = false;
inline bool active() { return detailed || qualification; }
inline void mark(const char* name, qint64 value = 0, bool outer = false) {
  if (!outer && !active()) return;
  const auto timestamp = now();
  if (used == recordLimit) {
    failed = true;
    return;
  }
  ledger[used++] = {name, timestamp, value};
}
inline void drain(QProcess& process) {
  process.setReadChannel(QProcess::StandardError);
  while (process.bytesAvailable()) {
    const auto bytes = process.read(qMin<qint64>(4096, process.bytesAvailable()));
    const auto room = byteLimit - errors.size();
    errors += bytes.left(room);
    if (bytes.size() > room) failed = true;
  }
  process.setReadChannel(QProcess::StandardOutput);
}
inline void identity(const QString& unit) {
  QFile file(journal);
  if (!file.open(QIODevice::WriteOnly) || file.write(unit.toUtf8()) != unit.size() || !file.flush())
    throw std::runtime_error("watchdog unit journal");
}
inline void clockInfo() {
  struct stat info{};
  timespec resolution{};
  QFile offsets("/proc/self/timens_offsets");
  if (stat("/proc/self/ns/time", &info) || clock_getres(CLOCK_MONOTONIC, &resolution) ||
      !offsets.open(QIODevice::ReadOnly))
    throw std::runtime_error("clock identity");
  mark("clock_inode", info.st_ino);
  mark("clock_resolution", resolution.tv_sec * 1000000000LL + resolution.tv_nsec);
  const auto data = offsets.readAll();
  // Require the kernel's explicit zero offsets, not a guessed alignment.
  for (const auto& line : data.split('\n')) {
    const auto fields = line.simplified().split(' ');
    if (fields.size() == 3 && fields[0] == "monotonic") {
      mark("clock_sec", fields[1].toLongLong());
      mark("clock_nsec", fields[2].toLongLong());
      return;
    }
  }
  throw std::runtime_error("clock offsets");
}
inline QJsonArray json() {
  QJsonArray result;
  for (size_t i = 0; i < used; ++i)
    result.append(QJsonObject{{"mark", ledger[i].mark},
                              {"ns", ledger[i].ns},
                              {"value", ledger[i].value},
                              {"seq", qint64(i)},
                              {"pid", getpid()},
                              {"role", "parent"}});
  return result;
}
// Only helper processes use this fixed-size, single-write transport. No extra fd.
inline const char* role = "helper";
inline unsigned sequence = 0;
inline int writeErrors = 0;
inline bool childEnabled = false;
inline void child(const char* name, qint64 value = 0, qint64 timestamp = 0) {
  if (!childEnabled) return;
  char bytes[512];
  const int length = snprintf(bytes, sizeof bytes, "LRP1 %s %u %d %s %lld %lld\n", role, sequence++, getpid(), name,
                              static_cast<long long>(timestamp ? timestamp : now()), static_cast<long long>(value));
  if (length <= 0 || length >= int(sizeof bytes) || ::write(2, bytes, length) != length) ++writeErrors;
}
inline void childStart(bool gate, bool qualify, qint64 entry) {
  role = gate ? "gate" : "helper";
  childEnabled = detailed || qualify;
  if (!childEnabled) return;
  const int flags = fcntl(2, F_GETFL);
  if (flags < 0 || fcntl(2, F_SETFL, flags | O_NONBLOCK) < 0 || fpathconf(2, _PC_PIPE_BUF) < 512) _exit(79);
  if (!gate) child("H", 0, entry);
  struct stat info{};
  timespec resolution{};
  if (stat("/proc/self/ns/time", &info) || clock_getres(CLOCK_MONOTONIC, &resolution)) {
    ++writeErrors;
    return;
  }
  child("clock_inode", info.st_ino);
  child("clock_resolution", resolution.tv_sec * 1000000000LL + resolution.tv_nsec);
  int fd = open("/proc/self/timens_offsets", O_RDONLY | O_CLOEXEC);
  char buffer[256]{};
  const auto length = fd < 0 ? -1 : read(fd, buffer, sizeof buffer - 1);
  if (fd >= 0) close(fd);
  long long sec = -1, ns = -1;
  if (length <= 0 || sscanf(buffer, "monotonic %lld %lld", &sec, &ns) != 2) {
    ++writeErrors;
    return;
  }
  child("clock_sec", sec);
  child("clock_nsec", ns);
}
struct Trailer {
  ~Trailer() { child("T", writeErrors); }
};
inline void spawnDescendant() {
  const auto pid = fork();
  if (pid < 0) _exit(80);
  if (!pid) {
    signal(SIGTERM, SIG_IGN);
    role = "descendant";
    sequence = 0;
    child("descendant", getpid());
    for (;;) pause();
  }
}
inline void helperFault(const char* name) {
  if (!strcmp(name, "failed")) {
    child("fault", 1);
    _exit(76);
  }
  if (!strcmp(name, "await") || !strcmp(name, "timeout") || !strcmp(name, "descendant")) {
    child("fault", 2);
    for (;;) pause();
  }
}
}  // namespace Profile
