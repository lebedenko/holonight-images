// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QElapsedTimer>
#include <QJsonArray>
#include <QJsonObject>
#include <vector>

namespace Profile {
struct Event {
  const char* phase;
  QString path;
  qint64 bytes;
  qint64 ns;
};
inline std::vector<Event> events;
// Only the private overlay constructs this recorder. No output during validation.
struct Recorder {
  QElapsedTimer clock;
  const char* phase = "manifest_load_parse";
  QString path;
  qint64 bytes = -1;
  Recorder() { clock.start(); }
  void mark(const char* next, const QString& name = {}, qint64 size = -1) {
    const auto elapsed = clock.nsecsElapsed();
    events.push_back({phase, path, bytes, elapsed});
    phase = next;
    path = name;
    bytes = size;
    clock.start();
  }
  ~Recorder() { mark("done"); }
};
inline QJsonArray json() {
  QJsonArray result;
  for (const auto& event : events) {
    QJsonObject row{{"phase", event.phase}, {"path", event.path}, {"ns", event.ns}};
    row["bytes"] = event.bytes < 0 ? QJsonValue() : QJsonValue(event.bytes);
    result.append(row);
  }
  return result;
}
}  // namespace Profile
