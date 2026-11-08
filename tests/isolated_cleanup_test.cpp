// SPDX-License-Identifier: GPL-3.0-or-later
#include "../src/isolated/cleanup.h"

#include <QFile>
#include <QJsonDocument>
#include <QTemporaryDir>

#include <functional>
#include <gtest/gtest.h>
using namespace HolonightImages;
using namespace HolonightImages::Isolation;
namespace {
struct Fake final : CleanupOperations {
  qint64 time = 0;
  GroupState state = GroupState::Empty;
  int launcher = QProcess::NotRunning;
  bool reap = true;
  QStringList commands;
  std::function<ManagerResult(const QStringList&)> execute = [](const QStringList&) {
    return ManagerResult{.started = true, .exit_code = 0, .exit_status = QProcess::NormalExit};
  };
  qint64 now() override { return time; }
  GroupState observe(const QString& /*group*/) override { return state; }
  int launcherState() override { return launcher; }
  void waitLauncher(qint64 milliseconds) override {
    if (reap) {
      launcher = QProcess::NotRunning;
    } else {
      time += milliseconds;
    }
  }
  void killLauncher() override {}
  void pause() override { time += 5; }
  ManagerResult manager(const QStringList& args, qint64 /*remaining*/) override {
    commands.append(args.join(' '));
    return execute(args);
  }
};
TEST(Cleanup, EmptyAndRemovedNeedNoManagerCommands) {
  for (auto state : {GroupState::Empty, GroupState::Removed}) {
    Fake fake;
    fake.state = state;
    const auto report = cleanup(fake, "test.scope", "/group");
    EXPECT_TRUE(report.verified);
    EXPECT_FALSE(report.proof.isEmpty());
    EXPECT_TRUE(fake.commands.isEmpty());
  }
}
TEST(Cleanup, MissingIdentityCanBeProvenByManager) {
  Fake fake;
  fake.execute = [](const QStringList& args) {
    return ManagerResult{
        .started = true,
        .exit_code = 0,
        .exit_status = 0,
        .output = args.contains("--property=LoadState") ? "not-found" : "",
    };
  };
  EXPECT_TRUE(cleanup(fake, "test.scope", {}).verified);
}
TEST(Cleanup, DisappearanceDuringQueryOrSignals) {
  for (const auto& phase : {QString("show"), QString("--signal=TERM"), QString("--signal=KILL")}) {
    Fake fake;
    fake.state = GroupState::Populated;
    fake.execute = [&](const QStringList& args) {
      if (args.contains(phase)) {
        fake.state = GroupState::Removed;
      }
      return ManagerResult{
          .started = true,
          .exit_code = args.contains(phase) && phase != "show" ? 1 : 0,
          .exit_status = 0,
          .output = "/test.scope",
      };
    };
    EXPECT_TRUE(cleanup(fake, "test.scope", phase == "show" ? "" : "/group").verified);
  }
}
TEST(Cleanup, ManagerFailuresRemainAttributable) {
  for (int kind = 0; kind < 4; ++kind) {
    Fake fake;
    fake.execute = [kind](const QStringList&) {
      return ManagerResult{
          .started = kind != 0,
          .timed_out = kind == 2,
          .exit_code = kind == 1 ? 1 : 0,
          .exit_status = 0,
          .error = "manager error",
          .output = "malformed",
          .errors = "stderr",
      };
    };
    const auto report = cleanup(fake, "test.scope", {});
    EXPECT_FALSE(report.verified);
    EXPECT_EQ(report.stage, "scope-identity");
    const auto json =
        QJsonDocument::fromJson(failureDiagnostic(RuntimeStatus::Timeout, "original", &report).toUtf8()).object();
    EXPECT_EQ(json["operation"].toObject()["message"].toString(), "original");
    EXPECT_FALSE(json["cleanup"].toObject()["commands"].toArray().isEmpty());
  }
}
TEST(Cleanup, TermResistantDescendantsRequireKill) {
  Fake fake;
  fake.state = GroupState::Populated;
  fake.execute = [&](const QStringList& args) {
    if (args.contains("--signal=KILL")) {
      fake.state = GroupState::Empty;
    }
    return ManagerResult{.started = true, .exit_code = 0, .exit_status = 0};
  };
  EXPECT_TRUE(cleanup(fake, "test.scope", "/group").verified);
  EXPECT_EQ(fake.time, 1000);
  EXPECT_EQ(fake.commands.size(), 2);
}
TEST(Cleanup, UnknownAndPopulatedNeverProveCleanup) {
  for (auto state : {GroupState::Populated, GroupState::Unavailable, GroupState::Unreadable, GroupState::Malformed}) {
    Fake fake;
    fake.state = state;
    const auto report = cleanup(fake, "test.scope", "/group");
    EXPECT_FALSE(report.verified);
    EXPECT_TRUE(report.proof.isEmpty());
    EXPECT_LE(report.elapsed, 5001);
  }
}
TEST(Cleanup, UnreapedLauncherSuppressesResults) {
  Fake fake;
  fake.launcher = QProcess::Running;
  fake.reap = false;
  const auto report = cleanup(fake, "test.scope", "/group");
  EXPECT_FALSE(report.verified);
  EXPECT_EQ(report.stage, "launcher-reaping");
  TransportResult result{.status = RuntimeStatus::Success, .reply = Reply{}};
  finishCleanup(result, RuntimeStatus::Success, {}, &report, true);
  EXPECT_EQ(result.status, RuntimeStatus::CleanupFailure);
  EXPECT_FALSE(result.reply);
}
TEST(Cleanup, CancellationDuringCompletionOrCleanupWinsDelivery) {
  for (bool during : {false, true}) {
    Fake fake;
    bool cancelled = !during;
    fake.state = during ? GroupState::Populated : GroupState::Empty;
    fake.execute = [&](const QStringList&) {
      cancelled = true;
      fake.state = GroupState::Empty;
      return ManagerResult{.started = true, .exit_code = 0, .exit_status = 0};
    };
    const auto report = cleanup(fake, "test.scope", "/group");
    TransportResult result{.status = RuntimeStatus::Success, .reply = Reply{}};
    finishCleanup(result, RuntimeStatus::Success, {}, &report, cancelled);
    EXPECT_EQ(result.status, RuntimeStatus::Cancelled);
    EXPECT_FALSE(result.reply);
  }
}
TEST(Cleanup, CleanupFailurePreservesTheOperationFailureEvenWhenCancelled) {
  CleanupReport report;
  report.stage = "term";
  TransportResult result{.status = RuntimeStatus::Timeout, .diagnostic = "request deadline"};
  finishCleanup(result, result.status, result.diagnostic, &report, true);
  EXPECT_EQ(result.status, RuntimeStatus::CleanupFailure);
  const auto original = QJsonDocument::fromJson(result.diagnostic.toUtf8()).object()["operation"].toObject();
  EXPECT_EQ(original["status"].toInt(), static_cast<int>(RuntimeStatus::Timeout));
  EXPECT_EQ(original["message"].toString(), "request deadline");
}
TEST(Cleanup, SerializationIsBoundedAndPreservesOriginalFailure) {
  CleanupReport report;
  for (int i = 0; i < 10; ++i) {
    report.commands.append(ManagerResult{.output = QByteArray(10000, '\1'), .errors = QByteArray(10000, 'e')});
  }
  auto bytes = failureDiagnostic(RuntimeStatus::ProtocolFailure, "helper EOF", &report).toUtf8();
  EXPECT_LE(bytes.size(), 65536);
  auto json = QJsonDocument::fromJson(bytes).object();
  EXPECT_EQ(json["operation"].toObject()["message"].toString(), "helper EOF");
  EXPECT_TRUE(json["truncated"].toBool());
  EXPECT_EQ(json["cleanup"].toObject()["commands"].toArray().size(), 10);
  EXPECT_TRUE(bytes.contains("[truncated]"));
}
TEST(Cleanup, ObservationRequiresUnambiguousPopulatedValue) {
  QTemporaryDir directory;
  QFile events(directory.path() + "/cgroup.events");
  EXPECT_EQ(observeGroup(directory.path()), GroupState::Unreadable);
  for (const auto& bytes :
       {QByteArray("populated 0\npopulated 1\n"), QByteArray("populated x\n"), QByteArray("frozen 0\n")}) {
    ASSERT_TRUE(events.open(QIODevice::WriteOnly | QIODevice::Truncate));
    events.write(bytes);
    events.close();
    EXPECT_EQ(observeGroup(directory.path()), GroupState::Malformed);
  }
  for (const auto& populated : {QByteArray("0"), QByteArray("1")}) {
    ASSERT_TRUE(events.open(QIODevice::WriteOnly | QIODevice::Truncate));
    events.write("populated " + populated + "\nfrozen 0\n");
    events.close();
    EXPECT_EQ(observeGroup(directory.path()), populated == "0" ? GroupState::Empty : GroupState::Populated);
  }
  // ENOTDIR is an unavailable observation, not evidence of a removed scope.
  EXPECT_EQ(observeGroup(events.fileName() + "/child"), GroupState::Unreadable);
  EXPECT_EQ(observeGroup(directory.path() + "/missing"), GroupState::Removed);
  EXPECT_EQ(observeGroup({}), GroupState::Unavailable);
}
}  // namespace
