// SPDX-License-Identifier: GPL-3.0-or-later
#include "cleanup.h"

#include <QDir>
#include <QFile>
#include <QJsonDocument>

#include <cerrno>
#include <sys/stat.h>

namespace HolonightImages::Isolation {
namespace {
QString stateName(GroupState state) {
  switch (state) {
    case GroupState::Removed:
      return "removed";
    case GroupState::Empty:
      return "populated-zero";
    case GroupState::Populated:
      return "populated";
    case GroupState::Unavailable:
      return "unavailable";
    case GroupState::Unreadable:
      return "unreadable";
    case GroupState::Malformed:
      return "malformed";
  }
  return "unavailable";
}
QString bounded(const QByteArray& bytes, bool truncated = false) {
  constexpr int limit = 4096;
  const QByteArray marker("...[truncated]");
  if (truncated || bytes.size() > limit) {
    return QString::fromUtf8(bytes.left(limit - marker.size()) + marker);
  }
  return QString::fromUtf8(bytes);
}
}  // namespace
bool ManagerResult::ok() const {
  return started && !timed_out && exit_status == QProcess::NormalExit && exit_code == 0;
}
GroupState observeGroup(const QString& group) {
  if (group.isEmpty()) {
    return GroupState::Unavailable;
  }
  struct stat info{};
  if (stat(QFile::encodeName(group).constData(), &info) != 0) {
    return errno == ENOENT ? GroupState::Removed : GroupState::Unreadable;
  }
  QFile events(group + "/cgroup.events");
  if (!events.open(QIODevice::ReadOnly)) {
    return GroupState::Unreadable;
  }
  const auto bytes = events.read(4097);
  if (events.error() != QFile::NoError) {
    return GroupState::Unreadable;
  }
  if (bytes.size() > 4096) {
    return GroupState::Malformed;
  }
  int count = 0;
  GroupState state = GroupState::Malformed;
  for (const auto& line : bytes.split('\n')) {
    if (line.startsWith("populated ")) {
      ++count;
      if (line == "populated 0") {
        state = GroupState::Empty;
      } else if (line == "populated 1") {
        state = GroupState::Populated;
      } else {
        return GroupState::Malformed;
      }
    }
  }
  return count == 1 ? state : GroupState::Malformed;
}
// Keep the lifecycle sequence together for auditing.
// NOLINTNEXTLINE(readability-function-cognitive-complexity)
CleanupReport cleanup(CleanupOperations& ops, const QString& unit, QString group) {
  CleanupReport report;
  report.unit = unit;
  const auto start = ops.now();
  auto remaining = [&] { return qMax<qint64>(0, 5000 - (ops.now() - start)); };
  auto command = [&](const QStringList& args) {
    auto value = ops.manager(args, qMax<qint64>(1, remaining()));
    value.arguments = args;
    report.commands.append(value);
    return value;
  };
  auto empty = [&] {
    report.observation = ops.observe(group);
    const bool proven = report.observation == GroupState::Removed || report.observation == GroupState::Empty;
    report.proof = proven ? stateName(report.observation) : QString{};
    return proven;
  };
  auto done = [&] {
    report.group = group;
    report.elapsed = ops.now() - start;
    report.launcher_state = ops.launcherState();
    return report;
  };
  try {
    report.stage = "scope-identity";
    if (group.isEmpty()) {
      const auto query = command({"show", "--property=ControlGroup", "--value", unit});
      if (!query.ok()) {
        throw ProtocolError("manager");
      }
      const auto path = QString::fromUtf8(query.output).trimmed();
      if (!query.output_truncated && !path.isEmpty() && path.startsWith('/') && QDir::cleanPath(path) == path &&
          path.endsWith('/' + unit)) {
        group = "/sys/fs/cgroup" + path;
      } else {
        ops.waitLauncher(50);
        if (ops.launcherState() == QProcess::NotRunning) {
          const auto load = command({"show", "--property=LoadState", "--value", unit});
          if (load.ok() && !load.output_truncated && load.output.trimmed() == "not-found") {
            report.verified = true;
            report.proof = "manager-not-found";
            report.stage.clear();
            return done();
          }
        }
        throw ProtocolError("identity");
      }
    }
    if (!empty()) {
      report.stage = "term";
      if (!command({"kill", "--signal=TERM", unit}).ok() && !empty()) {
        throw ProtocolError("term");
      }
      const auto grace = ops.now();
      while (!empty() && ops.now() - grace < 1000 && remaining() > 0) {
        ops.pause();
      }
      if (!empty()) {
        report.stage = "kill";
        if (!command({"kill", "--signal=KILL", unit}).ok() && !empty()) {
          throw ProtocolError("kill");
        }
      }
    }
    report.stage = "hierarchical-proof";
    while (!empty() && remaining() > 0) {
      ops.pause();
    }
    if (ops.launcherState() != QProcess::NotRunning) {
      ops.waitLauncher(qMax<qint64>(1, remaining()));
    }
    if (remaining() > 0 && empty() && ops.launcherState() == QProcess::NotRunning) {
      report.verified = true;
      report.stage.clear();
      return done();
    }
    if (ops.launcherState() != QProcess::NotRunning) {
      report.stage = "launcher-reaping";
    }
  } catch (const ProtocolError&) {
  }
  ops.killLauncher();
  ops.waitLauncher(qMax<qint64>(1, remaining()));
  return done();
}
QString failureDiagnostic(RuntimeStatus original, const QString& message, const CleanupReport* report) {
  QJsonObject root{
      {"version", 1},
      {"operation", QJsonObject{{"status", static_cast<int>(original)}, {"message", bounded(message.toUtf8())}}},
  };
  if (report != nullptr) {
    QJsonArray commands;
    for (const auto& command : report->commands) {
      commands.append(QJsonObject{
          {"arguments", QJsonArray::fromStringList(command.arguments)},
          {"started", command.started},
          {"timed_out", command.timed_out},
          {"exit_code", command.exit_code},
          {"exit_status", command.exit_status},
          {"error", bounded(command.error.toUtf8())},
          {"stdout", bounded(command.output, command.output_truncated)},
          {"stderr", bounded(command.errors, command.errors_truncated)},
      });
    }
    root.insert("cleanup", QJsonObject{
                               {"verified", report->verified},
                               {"stage", report->stage},
                               {"elapsed_ms", report->elapsed},
                               {"unit", report->unit},
                               {"group", report->group},
                               {"proof", report->proof},
                               {"observation", stateName(report->observation)},
                               {"launcher_state", report->launcher_state},
                               {"commands", commands},
                           });
  }
  auto bytes = QJsonDocument(root).toJson(QJsonDocument::Compact);
  // JSON escaping can expand bounded streams sixfold. Shorten text before
  // discarding any command outcomes, preserving start/exit/timeout attribution.
  while (bytes.size() > 65536) {
    root.insert("truncated", true);
    auto object = root["cleanup"].toObject();
    auto commands = object["commands"].toArray();
    bool shortened = false;
    for (qsizetype index = 0; index < commands.size(); ++index) {
      auto command = commands[index].toObject();
      for (const auto* key : {"stdout", "stderr", "error"}) {
        const auto value = command[key].toString();
        if (value.size() > 64) {
          command.insert(key, value.left(value.size() / 2) + "...[truncated]");
          shortened = true;
        }
      }
      commands[index] = command;
    }
    if (!shortened) {
      // Production has at most four commands and bounded scope names. Retain
      // valid JSON even for an oversized report supplied by a private test.
      if (commands.isEmpty()) {
        root.insert("cleanup", QJsonObject{{"verified", report->verified}, {"truncated", true}});
        bytes = QJsonDocument(root).toJson(QJsonDocument::Compact);
        break;
      }
      commands.removeLast();
    }
    object.insert("commands", commands);
    root.insert("cleanup", object);
    bytes = QJsonDocument(root).toJson(QJsonDocument::Compact);
  }
  return QString::fromUtf8(bytes);
}
void finishCleanup(TransportResult& result, RuntimeStatus original, const QString& message, const CleanupReport* report,
                   bool cancelled) {
  if ((report != nullptr) && !report->verified) {
    result.status = RuntimeStatus::CleanupFailure;
  }
  if (cancelled && result.status != RuntimeStatus::CleanupFailure) {
    result.status = RuntimeStatus::Cancelled;
  }
  if (result.status != RuntimeStatus::Success) {
    result.reply.reset();
    result.diagnostic = failureDiagnostic(original, message, report);
  }
}
}  // namespace HolonightImages::Isolation
