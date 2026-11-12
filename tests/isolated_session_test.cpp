// SPDX-License-Identifier: GPL-3.0-or-later
#include <QBuffer>
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QProcess>
#include <QProcessEnvironment>
#include <QThread>

#include <chrono>
#include <cstdio>
#include <fcntl.h>
#include <gtest/gtest.h>
#include <holonight_images/isolated.h>
#include <sys/file.h>
#include <thread>
#include <unistd.h>
using namespace HolonightImages;
TEST(SessionPreparation, CancellationDuringLaunchRetainsCleanupIdentity) {
  const auto runtime = qEnvironmentVariable("HN_SESSION_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "explicit protected native fixture required";
  }
  RuntimeOwner owner(runtime);
  ASSERT_TRUE(owner.acquire()) << owner.diagnostic().toStdString();
  for (int attempt = 0; attempt < 24; ++attempt) {
    ReusableSession session(owner.acquire());
    std::atomic_bool cancel{false};
    std::jthread cancellation([&] {
      std::this_thread::sleep_for(std::chrono::microseconds(500 * (attempt % 8)));
      cancel.store(true);
    });
    const auto prepared = session.prepare(cancel);
    cancellation.join();
    EXPECT_TRUE(prepared.runtime == RuntimeStatus::Cancelled || prepared.runtime == RuntimeStatus::Success)
        << prepared.diagnostic.toStdString();
    EXPECT_EQ(session.retire().runtime, RuntimeStatus::Success);
    ASSERT_FALSE(owner.launchesDisabled()) << owner.diagnostic().toStdString();
  }
}
namespace {
const Limits limits{.inputBytes = 1048576,
                    .sourcePixels = 100000,
                    .sourceExtent = 1000,
                    .decodedBytes = 1048576,
                    .metadataBytes = 1024,
                    .tiffMetadataBytes = 1024,
                    .metadataRecords = 100};
class NativeSession : public testing::Test {
 protected:
  // GoogleTest generates derived tests that share this fixture state.
  // NOLINTBEGIN(cppcoreguidelines-non-private-member-variables-in-classes)
  std::unique_ptr<RuntimeOwner> owner;
  std::unique_ptr<ReusableSession> session;
  std::atomic_bool cancelled{false};
  // NOLINTEND(cppcoreguidelines-non-private-member-variables-in-classes)
  void SetUp() override {
    const auto path = qEnvironmentVariable("HN_SESSION_RUNTIME");
    if (path.isEmpty()) {
      GTEST_SKIP() << "explicit protected native fixture required";
    }
    owner = std::make_unique<RuntimeOwner>(path);
    ASSERT_TRUE(owner->acquire()) << owner->diagnostic().toStdString();
    session = std::make_unique<ReusableSession>(owner->acquire());
    const auto prepared = session->prepare(cancelled);
    ASSERT_EQ(prepared.runtime, RuntimeStatus::Success) << prepared.diagnostic.toStdString();
  }
};
TEST_F(NativeSession, RepeatedTransactionsKeepReadinessAndSourceIsolation) {
  int started = 0;
  session->setTransactionStartedCallback([&] { ++started; });
  for (int number = 0; number < 40; ++number) {
    const auto color = number % 2 != 0 ? QColor(Qt::red) : QColor(Qt::blue);
    QImage image(30, 20, QImage::Format_RGB32);
    image.fill(color);
    QBuffer source;
    ASSERT_TRUE(source.open(QIODevice::ReadWrite));
    ASSERT_TRUE(image.save(&source, "PNG"));
    const auto result =
        session->sourceTransaction(source, limits, cancelled, [](const Inspection&, SourceTransaction& transaction) {
          return transaction.decodeSource({.limits = limits, .bound = {30, 20}});
        });
    ASSERT_EQ(result.runtime, RuntimeStatus::Success) << result.diagnostic.toStdString();
    ASSERT_TRUE(result.result);
    EXPECT_TRUE(result.completionAcknowledged);
    EXPECT_TRUE(static_cast<bool>(result));
    EXPECT_EQ(result.result->image.pixelColor(0, 0), color);
    ASSERT_TRUE(session->ready());
    ASSERT_GT(session->idleMemoryBytes(), 0);
  }
  EXPECT_EQ(started, 40);
  EXPECT_EQ(session->retire().runtime, RuntimeStatus::Success);
  EXPECT_FALSE(session->ready());
}
TEST_F(NativeSession, CancellationBeforeDispatchPreservesReadiness) {
  QBuffer source;
  source.open(QIODevice::ReadWrite);
  int started = 0;
  session->setTransactionStartedCallback([&] { ++started; });
  cancelled.store(true);
  const auto result = session->sourceTransaction(source, limits, cancelled, {});
  EXPECT_EQ(result.runtime, RuntimeStatus::Cancelled);
  EXPECT_TRUE(session->ready());
  EXPECT_EQ(started, 0);
  cancelled.store(false);
  EXPECT_EQ(session->retire().runtime, RuntimeStatus::Success);
}
TEST_F(NativeSession, CallbackExceptionPoisonsAndRetiresSession) {
  QImage image(30, 20, QImage::Format_RGB32);
  image.fill(Qt::red);
  QBuffer source;
  ASSERT_TRUE(source.open(QIODevice::ReadWrite));
  ASSERT_TRUE(image.save(&source, "PNG"));
  const auto result = session->sourceTransaction(
      source, limits, cancelled,
      [](const Inspection&, SourceTransaction&) -> DecodeResult { throw std::runtime_error("callback failure"); });
  EXPECT_EQ(result.runtime, RuntimeStatus::ProtocolFailure) << result.diagnostic.toStdString();
  EXPECT_FALSE(result.result);
  EXPECT_FALSE(session->ready());
}
TEST_F(NativeSession, CancellationAfterInspectionPoisonsTheDispatchedSession) {
  QImage image(30, 20, QImage::Format_RGB32);
  image.fill(Qt::red);
  QBuffer source;
  ASSERT_TRUE(source.open(QIODevice::ReadWrite));
  ASSERT_TRUE(image.save(&source, "PNG"));
  const auto result =
      session->sourceTransaction(source, limits, cancelled, [&](const Inspection& inspection, SourceTransaction&) {
        cancelled.store(true);
        DecodeResult selected;
        selected.outcome = inspection.outcome;
        return selected;
      });
  EXPECT_EQ(result.runtime, RuntimeStatus::Cancelled) << result.diagnostic.toStdString();
  EXPECT_FALSE(result.completionAcknowledged);
  EXPECT_FALSE(session->ready());
}
TEST_F(NativeSession, LocalRejectionPreservesReadinessWithoutClaimingCompletion) {
  QBuffer source;
  source.open(QIODevice::ReadWrite);
  auto invalid = limits;
  invalid.inputBytes = 0;
  const auto result = session->sourceTransaction(source, invalid, cancelled, {});
  EXPECT_EQ(result.runtime, RuntimeStatus::Success);
  ASSERT_TRUE(result.result);
  EXPECT_EQ(result.result->outcome, Outcome::ResourceLimit);
  EXPECT_FALSE(result.completionAcknowledged);
  EXPECT_FALSE(static_cast<bool>(result));
  EXPECT_TRUE(session->ready());
}
class NativeSessionFault : public NativeSession {
 protected:
  void SetUp() override {
    const auto runtime = qEnvironmentVariable("HN_SESSION_FAULT_RUNTIME");
    if (runtime.isEmpty()) {
      GTEST_SKIP() << "explicit protected session-fault fixture required";
    }
    owner = std::make_unique<RuntimeOwner>(runtime);
    ASSERT_TRUE(owner->acquire()) << owner->diagnostic().toStdString();
    session = std::make_unique<ReusableSession>(owner->acquire());
    const auto prepared = session->prepare(cancelled);
    ASSERT_EQ(prepared.runtime, RuntimeStatus::Success) << prepared.diagnostic.toStdString();
  }
  SessionResult<DecodeResult> request(const QByteArray& mode) {
    QBuffer source;
    source.setData(mode);
    source.open(QIODevice::ReadOnly);
    return session->sourceTransaction(source, limits, cancelled, [](const Inspection& inspection, SourceTransaction&) {
      DecodeResult selected;
      selected.outcome = inspection.outcome;
      return selected;
    });
  }
};
TEST_F(NativeSessionFault, RejectsMalformedMismatchedAndCrashedResponses) {
  for (const auto* mode :
       {"session-identity", "session-sequence", "session-malformed", "session-crash", "session-ack-identity"}) {
    if (!session->ready()) {
      session = std::make_unique<ReusableSession>(owner->acquire());
      ASSERT_EQ(session->prepare(cancelled).runtime, RuntimeStatus::Success);
    }
    const auto result = request(mode);
    EXPECT_EQ(result.runtime, RuntimeStatus::ProtocolFailure) << mode << result.diagnostic.toStdString();
    EXPECT_FALSE(result.completionAcknowledged);
    EXPECT_FALSE(session->ready());
    EXPECT_EQ(session->retire().runtime, RuntimeStatus::Success);
  }
}
TEST_F(NativeSessionFault, IdleOutputAndCrashPoisonWithoutAnotherRequest) {
  for (const auto* mode : {"session-idle-output", "session-idle-exit"}) {
    if (!session->ready()) {
      session = std::make_unique<ReusableSession>(owner->acquire());
      ASSERT_EQ(session->prepare(cancelled).runtime, RuntimeStatus::Success);
    }
    const auto result = request(mode);
    ASSERT_TRUE(static_cast<bool>(result)) << result.diagnostic.toStdString();
    QElapsedTimer deadline;
    deadline.start();
    while (session->ready() && deadline.elapsed() < 6000) {
      QCoreApplication::processEvents();
      QThread::msleep(1);
    }
    EXPECT_FALSE(session->ready());
    EXPECT_EQ(session->retire().runtime, RuntimeStatus::Success);
  }
}
TEST_F(NativeSessionFault, ActiveDeadlineRetiresTheSession) {
  QElapsedTimer deadline;
  deadline.start();
  const auto result = request("session-hang");
  EXPECT_EQ(result.runtime, RuntimeStatus::Timeout) << result.diagnostic.toStdString();
  EXPECT_FALSE(result.completionAcknowledged);
  EXPECT_FALSE(session->ready());
  EXPECT_GE(deadline.elapsed(), 14000);
  EXPECT_LT(deadline.elapsed(), 22000);
}
TEST_F(NativeSessionFault, RetirementRemovesDescendants) {
  const auto result = request("session-descendant");
  ASSERT_TRUE(static_cast<bool>(result)) << result.diagnostic.toStdString();
  EXPECT_EQ(session->retire().runtime, RuntimeStatus::Success);
  for (const auto& pid : QDir("/proc").entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
    QFile name("/proc/" + pid + "/comm");
    if (name.open(QIODevice::ReadOnly)) {
      EXPECT_NE(name.readAll().trimmed(), "hn-session-kid");
    }
  }
}
TEST(SessionStartup, StartupDeadlineIsSeparateAndVerified) {
  const auto runtime = qEnvironmentVariable("HN_SESSION_STARTUP_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "explicit protected startup-fault fixture required";
  }
  RuntimeOwner owner(runtime);
  ASSERT_TRUE(owner.acquire()) << owner.diagnostic().toStdString();
  ReusableSession session(owner.acquire());
  const std::atomic_bool cancelled{false};
  QElapsedTimer deadline;
  deadline.start();
  const auto prepared = session.prepare(cancelled);
  EXPECT_EQ(prepared.runtime, RuntimeStatus::Timeout) << prepared.diagnostic.toStdString();
  EXPECT_FALSE(session.ready());
  EXPECT_GE(deadline.elapsed(), 14000);
  EXPECT_LT(deadline.elapsed(), 22000);
  EXPECT_EQ(session.retire().runtime, RuntimeStatus::Success);
}
int cleanupLeaseProbe(const QString& runtime) {
  {
    RuntimeOwner owner(runtime);
    if (!owner.acquire()) {
      return 21;
    }
    {
      ReusableSession session(owner.acquire());
      const std::atomic_bool cancelled{false};
      const auto prepared = session.prepare(cancelled);
      if (prepared.runtime != RuntimeStatus::CleanupFailure || !owner.launchesDisabled() || owner.acquire()) {
        return 22;
      }
      if (session.retire().runtime != RuntimeStatus::CleanupFailure || owner.refresh()) {
        return 23;
      }
    }
  }
  std::fputs("quarantined\n", stdout);
  std::fflush(stdout);
  char release = 0;
  return ::read(STDIN_FILENO, &release, 1) == 1 ? 0 : 24;
}
TEST(SessionCleanupLease, FailedCleanupPinsBeyondOwnerAndSessionUntilProcessExit) {
  const auto runtime = qEnvironmentVariable("HN_SESSION_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "explicit protected native fixture required";
  }
  QFile current(runtime + "/current");
  ASSERT_TRUE(current.open(QIODevice::ReadOnly));
  const auto path = runtime + "/generations/" + QString::fromLatin1(current.readAll().trimmed());
  const int descriptor = ::open(QFile::encodeName(path).constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  ASSERT_GE(descriptor, 0);
  ASSERT_EQ(flock(descriptor, LOCK_EX | LOCK_NB), 0);
  ASSERT_EQ(flock(descriptor, LOCK_UN), 0);
  QProcess probe;
  auto environment = QProcessEnvironment::systemEnvironment();
  environment.insert("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/holonight-nonexistent-test-bus");
  environment.insert("XDG_RUNTIME_DIR", "/run/holonight-nonexistent-test-runtime");
  probe.setProcessEnvironment(environment);
  probe.start(QCoreApplication::applicationFilePath(), {"--cleanup-lease-probe", runtime});
  ASSERT_TRUE(probe.waitForStarted());
  ASSERT_TRUE(probe.waitForReadyRead(10000)) << probe.readAllStandardError().constData();
  EXPECT_EQ(probe.readLine(), "quarantined\n");
  EXPECT_EQ(flock(descriptor, LOCK_EX | LOCK_NB), -1);
  probe.write("exit");
  probe.closeWriteChannel();
  ASSERT_TRUE(probe.waitForFinished(10000));
  EXPECT_EQ(probe.exitCode(), 0) << probe.readAllStandardError().constData();
  EXPECT_EQ(flock(descriptor, LOCK_EX | LOCK_NB), 0);
  close(descriptor);
}
}  // namespace
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  if (argc == 3 && QByteArray(argv[1]) == "--cleanup-lease-probe") {
    return cleanupLeaseProbe(QString::fromLocal8Bit(argv[2]));
  }
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
