// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "runtime.h"

#include <QJsonArray>
#include <QProcess>

namespace HolonightImages::Isolation {
enum class GroupState : unsigned char { Removed, Empty, Populated, Unavailable, Unreadable, Malformed };
struct ManagerResult {
  QStringList arguments;
  bool started = false;
  bool timed_out = false;
  int exit_code = -1;
  int exit_status = -1;
  QString error;
  QByteArray output;
  QByteArray errors;
  bool output_truncated = false;
  bool errors_truncated = false;
  [[nodiscard]] bool ok() const;
};
// Private, per-invocation boundary; no production environment switches or global overrides.
struct CleanupOperations {
  CleanupOperations() = default;
  CleanupOperations(const CleanupOperations&) = delete;
  CleanupOperations& operator=(const CleanupOperations&) = delete;
  CleanupOperations(CleanupOperations&&) = delete;
  CleanupOperations& operator=(CleanupOperations&&) = delete;
  virtual ~CleanupOperations() = default;
  virtual qint64 now() = 0;
  virtual ManagerResult manager(const QStringList& arguments, qint64 remaining) = 0;
  virtual GroupState observe(const QString& group) = 0;
  virtual int launcherState() = 0;
  virtual void waitLauncher(qint64 milliseconds) = 0;
  virtual void killLauncher() = 0;
  virtual void pause() = 0;
};
struct CleanupReport {
  bool verified = false;
  QString stage;
  QString unit;
  QString group;
  QString proof;
  GroupState observation = GroupState::Unavailable;
  int launcher_state = QProcess::NotRunning;
  qint64 elapsed = 0;
  QList<ManagerResult> commands;
};
GroupState observeGroup(const QString& group);
CleanupReport cleanup(CleanupOperations& ops, const QString& unit, QString group);
QString failureDiagnostic(RuntimeStatus original, const QString& message, const CleanupReport* report);
void finishCleanup(TransportResult& result, RuntimeStatus original, const QString& message, const CleanupReport* report,
                   bool cancelled);
}  // namespace HolonightImages::Isolation
