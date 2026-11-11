// SPDX-License-Identifier: GPL-3.0-or-later
#include "../src/isolated/protocol.h"

#include <QBuffer>
#include <QCoreApplication>
#include <QProcess>
#include <QtEndian>

#include <gtest/gtest.h>
using namespace HolonightImages;
using namespace HolonightImages::Isolation;
namespace {
const Limits limits{.inputBytes = 1048576,
                    .sourcePixels = 100000,
                    .sourceExtent = 1000,
                    .decodedBytes = 1048576,
                    .metadataBytes = 1024,
                    .tiffMetadataBytes = 1024,
                    .metadataRecords = 100};
QByteArray png(QColor color) {
  QImage image(30, 20, QImage::Format_ARGB32);
  image.fill(color);
  QByteArray bytes;
  QBuffer buffer(&bytes);
  buffer.open(QIODevice::WriteOnly);
  image.save(&buffer, "PNG");
  return bytes;
}
class TransactionHelper : public testing::Test {
 protected:
  QProcess process;
  QByteArray receive(qint64 count) {
    QByteArray bytes;
    while (bytes.size() < count) {
      bytes += process.read(count - bytes.size());
      if (bytes.size() < count && !process.waitForReadyRead(1000)) {
        throw ProtocolError("test helper EOF");
      }
    }
    return bytes;
  }
  void SetUp() override {
    process.start(QString::fromLocal8Bit(HELPER_PATH), {});
    ASSERT_TRUE(process.waitForStarted());
    ASSERT_EQ(receive(1), "R");
  }
  void TearDown() override {
    if (process.state() != QProcess::NotRunning) {
      process.kill();
      process.waitForFinished();
    }
  }
  void send(int sequence, bool retained, const Request& request, const QByteArray& bytes) {
    auto record = requestControl(request, bytes.size());
    record["transactionVersion"] = 1;
    record["sequence"] = sequence;
    record["retainedSource"] = retained;
    process.write(frame(record) + bytes);
    process.waitForBytesWritten();
  }
  Reply reply(int sequence, const Request& request) {
    const auto length = qFromBigEndian<quint32>(receive(4).constData());
    auto record = parseControl(receive(length));
    integer(record, "transactionVersion", 1, 1);
    integer(record, "sequence", sequence, sequence);
    return parseReply(record, receive(integer(record, "bytes", 0, limits.decodedBytes)), request);
  }
  void finish() {
    process.write("A");
    process.closeWriteChannel();
    ASSERT_TRUE(process.waitForFinished());
    ASSERT_EQ(process.exitCode(), 0);
    ASSERT_TRUE(process.readAllStandardOutput().isEmpty());
  }
};
const Request inspectRequest{
    .operation = Operation::Inspect, .options = {.limits = limits, .bound = {}}, .metadata = true};
const Request decodeRequest{
    .operation = Operation::Decode, .options = {.limits = limits, .bound = {30, 20}}, .metadata = true};
TEST_F(TransactionHelper, RetainsSourceAcrossRejectedCandidates) {
  send(0, false, inspectRequest, png(Qt::red));
  EXPECT_EQ(reply(0, inspectRequest).inspection.orientedSize, QSize(30, 20));
  for (int sequence = 1; sequence <= 4; ++sequence) {
    send(sequence, false, decodeRequest, "invalid PNG");
    EXPECT_EQ(reply(sequence, decodeRequest).decoded.outcome, Outcome::Unsupported);
  }
  send(5, true, decodeRequest, {});
  EXPECT_EQ(reply(5, decodeRequest).decoded.image.pixelColor(0, 0), QColor(Qt::red));
  finish();
}
TEST_F(TransactionHelper, CanSelectCachedPixelsWithoutSourceDecode) {
  send(0, false, inspectRequest, png(Qt::red));
  reply(0, inspectRequest);
  send(1, false, decodeRequest, png(Qt::blue));
  EXPECT_EQ(reply(1, decodeRequest).decoded.image.pixelColor(0, 0), QColor(Qt::blue));
  finish();
}
TEST_F(TransactionHelper, RejectsRepeatedInspection) {
  send(0, false, inspectRequest, png(Qt::red));
  reply(0, inspectRequest);
  send(1, false, inspectRequest, png(Qt::red));
  ASSERT_TRUE(process.waitForFinished());
  EXPECT_NE(process.exitCode(), 0);
}
TEST_F(TransactionHelper, RejectsFifthCandidate) {
  send(0, false, inspectRequest, png(Qt::red));
  reply(0, inspectRequest);
  for (int sequence = 1; sequence <= 4; ++sequence) {
    send(sequence, false, decodeRequest, "invalid");
    reply(sequence, decodeRequest);
  }
  send(5, false, decodeRequest, "invalid");
  ASSERT_TRUE(process.waitForFinished());
  EXPECT_NE(process.exitCode(), 0);
}
TEST_F(TransactionHelper, RejectsDecodeAfterSourceDecode) {
  send(0, false, inspectRequest, png(Qt::red));
  reply(0, inspectRequest);
  send(1, true, decodeRequest, {});
  reply(1, decodeRequest);
  send(2, false, decodeRequest, png(Qt::blue));
  ASSERT_TRUE(process.waitForFinished());
  EXPECT_NE(process.exitCode(), 0);
}
TEST_F(TransactionHelper, RejectsOutOfOrderIdentity) {
  send(0, false, inspectRequest, png(Qt::red));
  reply(0, inspectRequest);
  send(2, true, decodeRequest, {});
  ASSERT_TRUE(process.waitForFinished());
  EXPECT_NE(process.exitCode(), 0);
}
TEST(SourceTransaction, ReturnsOnlyFinalPixelsAndSourceFacts) {
  const auto runtime = qEnvironmentVariable("HN_TRANSACTION_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "native runtime required";
  }
  std::atomic_bool cancelled{false};
  auto bytes = png(Qt::red);
  QBuffer source(&bytes);
  source.open(QIODevice::ReadOnly);
  auto result = IsolatedClient(runtime).sourceTransaction(
      source, limits, cancelled, [&](const Inspection& inspection, SourceTransaction& transaction) {
        EXPECT_EQ(inspection.orientedSize, QSize(30, 20));
        // Mutating the caller device after capture must not affect source fallback.
        bytes = png(Qt::blue);
        auto rejected = QByteArray("invalid");
        QBuffer candidate(&rejected);
        candidate.open(QIODevice::ReadOnly);
        EXPECT_EQ(transaction.decodeCachedPng(candidate, decodeRequest.options).outcome, Outcome::Unsupported);
        return transaction.decodeSource(decodeRequest.options);
      });
  ASSERT_EQ(result.runtime, RuntimeStatus::Success) << result.diagnostic.toStdString();
  ASSERT_TRUE(result.result);
  EXPECT_EQ(result.result->image.pixelColor(0, 0), QColor(Qt::red));
  EXPECT_EQ(result.result->inspection.orientedSize, QSize(30, 20));
  EXPECT_TRUE(source.isOpen());
}
TEST(SourceTransaction, CancellationAndCallbackFailureDiscardResults) {
  const auto runtime = qEnvironmentVariable("HN_TRANSACTION_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "native runtime required";
  }
  for (int mode : {0, 1, 2}) {
    std::atomic_bool cancelled{false};
    auto bytes = png(Qt::red);
    QBuffer source(&bytes);
    source.open(QIODevice::ReadOnly);
    auto result = IsolatedClient(runtime).sourceTransaction(
        source, limits, cancelled, [&](const Inspection&, SourceTransaction& transaction) -> DecodeResult {
          auto decoded = transaction.decodeSource(decodeRequest.options);
          if (mode == 1) {
            cancelled.store(true);
            return decoded;
          }
          if (mode == 2) {
            throw 42;
          }
          throw std::runtime_error("coordination failed");
        });
    EXPECT_EQ(result.runtime, mode == 1 ? RuntimeStatus::Cancelled : RuntimeStatus::ProtocolFailure)
        << result.diagnostic.toStdString();
    EXPECT_FALSE(result.result);
  }
}
TEST(SourceTransaction, CaughtInvalidSequenceStillAborts) {
  const auto runtime = qEnvironmentVariable("HN_TRANSACTION_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "native runtime required";
  }
  std::atomic_bool cancelled{false};
  auto bytes = png(Qt::red);
  QBuffer source(&bytes);
  source.open(QIODevice::ReadOnly);
  auto result = IsolatedClient(runtime).sourceTransaction(
      source, limits, cancelled, [&](const Inspection&, SourceTransaction& transaction) {
        auto decoded = transaction.decodeSource(decodeRequest.options);
        try {
          transaction.decodeSource(decodeRequest.options);
        } catch (const std::exception&) {
        }
        return decoded;
      });
  EXPECT_EQ(result.runtime, RuntimeStatus::ProtocolFailure) << result.diagnostic.toStdString();
  EXPECT_FALSE(result.result);
}
TEST(SourceTransaction, StageFailuresDiscardInspectionAndPixels) {
  const auto runtime = qEnvironmentVariable("HN_TRANSACTION_FAULT_RUNTIME");
  if (runtime.isEmpty()) {
    GTEST_SKIP() << "native fault runtime required";
  }
  for (const auto* mode :
       {"txn-crash", "txn-malformed", "txn-partial", "txn-trailing", "txn-identity", "txn-hang", "txn-descendant"}) {
    SCOPED_TRACE(mode);
    std::atomic_bool cancelled{false};
    QByteArray bytes(mode);
    QBuffer source(&bytes);
    source.open(QIODevice::ReadOnly);
    auto result = IsolatedClient(runtime).sourceTransaction(source, limits, cancelled,
                                                            [&](const Inspection&, SourceTransaction& transaction) {
                                                              return transaction.decodeSource(decodeRequest.options);
                                                            });
    const bool timeout = bytes == "txn-hang" || bytes == "txn-descendant";
    EXPECT_EQ(result.runtime, timeout ? RuntimeStatus::Timeout : RuntimeStatus::ProtocolFailure)
        << result.diagnostic.toStdString();
    EXPECT_FALSE(result.result);
    if (result.runtime == RuntimeStatus::CleanupFailure) {
      FAIL() << "stop after unverified cleanup";
    }
  }
}
}  // namespace
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  testing::InitGoogleTest(&argc, argv);
  return RUN_ALL_TESTS();
}
