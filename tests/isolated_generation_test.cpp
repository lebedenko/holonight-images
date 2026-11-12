// SPDX-License-Identifier: GPL-3.0-or-later
#include "../src/isolated/generation.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QTemporaryDir>

#include <fcntl.h>
#include <gtest/gtest.h>
#include <holonight_images/isolated.h>
#include <semaphore>
#include <sys/file.h>
#include <thread>
#include <unistd.h>

using namespace HolonightImages;
namespace {
void write(const QString& path, const QByteArray& bytes) {
  QSaveFile file(path);
  ASSERT_TRUE(file.open(QIODevice::WriteOnly));
  ASSERT_EQ(file.write(bytes), bytes.size());
  ASSERT_TRUE(file.setPermissions(QFile::ReadOwner | QFile::WriteOwner | QFile::ReadGroup | QFile::ReadOther));
  ASSERT_TRUE(file.commit());
}
TEST(GenerationOwner, MutableAncestorCannotAuthorizeReuse) {
  QTemporaryDir directory;
  RuntimeOwner owner(directory.path());
  EXPECT_FALSE(owner.acquire());
  EXPECT_FALSE(owner.refresh());
  EXPECT_FALSE(owner.diagnostic().isEmpty());
}
class ProtectedGeneration : public testing::Test {
 protected:
  // GoogleTest generates derived tests that share this fixture state.
  // NOLINTBEGIN(cppcoreguidelines-non-private-member-variables-in-classes)
  std::unique_ptr<QTemporaryDir> directory;
  QString base;
  QByteArray first;
  // NOLINTEND(cppcoreguidelines-non-private-member-variables-in-classes)
  QByteArray create(const QByteArray& content, int protocol = -1) {
    QJsonArray inventory;
    for (const auto* path :
         {"usr/libexec/holonight-images-helper", "usr/lib/qt6/plugins/imageformats/libqgif.so",
          "usr/lib/qt6/plugins/imageformats/libqjpeg.so", "usr/lib/qt6/plugins/imageformats/libqtiff.so",
          "usr/lib/qt6/plugins/imageformats/libqwebp.so"}) {
      inventory.append(QJsonObject{
          {"path", path},
          {"mode", 0644},
          {"size", content.size()},
          {"sha256", QString::fromLatin1(QCryptographicHash::hash(content, QCryptographicHash::Sha256).toHex())}});
    }
    QJsonObject record{{"version", 1}, {"files", inventory}};
    if (protocol >= 0) {
      record["sessionProtocol"] = protocol;
    }
    const auto manifest = QJsonDocument(record).toJson();
    const auto name =
        QCryptographicHash::hash(QByteArray("holonight-images-policy-1\n") + manifest, QCryptographicHash::Sha256)
            .toHex();
    const auto root = base + "/generations/" + QString::fromLatin1(name);
    for (auto record : inventory) {
      const auto path = root + "/" + record.toObject()["path"].toString();
      QDir().mkpath(QFileInfo(path).path());
      write(path, content);
    }
    write(root + "/manifest.json", manifest);
    return name;
  }
  void select(const QByteArray& name) { write(base + "/current", name + "\n"); }
  void SetUp() override {
    if (geteuid() != 0) {
      GTEST_SKIP() << "protected fixture requires root and /run ancestors";
    }
    directory = std::make_unique<QTemporaryDir>("/run/holonight-generation-test-XXXXXX");
    ASSERT_TRUE(directory->isValid());
    base = directory->path();
    first = create("first");
    select(first);
  }
};
TEST_F(ProtectedGeneration, SharesLeaseUntilLastCopyAndPinsAcrossRefresh) {
  RuntimeOwner owner(base);
  auto held = owner.acquire();
  ASSERT_TRUE(held) << owner.diagnostic().toStdString();
  const auto old = held.runtimeDirectory();
  const auto fd = open(QFile::encodeName(old).constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  ASSERT_GE(fd, 0);
  EXPECT_EQ(flock(fd, LOCK_EX | LOCK_NB), -1);
  select(create("second"));
  ASSERT_TRUE(owner.refresh()) << owner.diagnostic().toStdString();
  EXPECT_NE(owner.acquire().runtimeDirectory(), old);
  EXPECT_EQ(flock(fd, LOCK_EX | LOCK_NB), -1);
  held = {};
  EXPECT_EQ(flock(fd, LOCK_EX | LOCK_NB), 0);
  close(fd);
}
TEST_F(ProtectedGeneration, FailedRefreshRevokesAcquisitionWithoutInvalidatingActiveLease) {
  RuntimeOwner owner(base);
  auto active = owner.acquire();
  ASSERT_TRUE(active);
  write(base + "/current", QByteArray(64, 'a') + "\n");
  EXPECT_FALSE(owner.refresh());
  EXPECT_FALSE(owner.acquire());
  EXPECT_TRUE(active);
  select(first);
  EXPECT_TRUE(owner.refresh());
}
TEST_F(ProtectedGeneration, ConcurrentAcquisitionObservesCompletedRefreshRevocation) {
  RuntimeOwner owner(base);
  const auto active = owner.acquire();
  ASSERT_TRUE(active);
  std::binary_semaphore began(0);
  std::binary_semaphore refreshed(0);
  std::atomic_bool stop{false};
  std::atomic_bool stale{false};
  std::thread reader([&] {
    began.release();
    while (!stop.load()) {
      (void)owner.acquire();
    }
    refreshed.acquire();
    for (int attempt = 0; attempt < 100; ++attempt) {
      if (owner.acquire()) {
        stale.store(true);
      }
    }
  });
  began.acquire();
  select(QByteArray(64, '0'));
  const bool accepted = owner.refresh();
  stop.store(true);
  refreshed.release();
  reader.join();
  EXPECT_FALSE(accepted);
  EXPECT_FALSE(stale.load());
  EXPECT_FALSE(owner.acquire());
  // Transactions that already acquired a lease still prevent removal.
  const auto fd = open(QFile::encodeName(active.runtimeDirectory()).constData(), O_RDONLY | O_DIRECTORY | O_CLOEXEC);
  ASSERT_GE(fd, 0);
  EXPECT_EQ(flock(fd, LOCK_EX | LOCK_NB), -1);
  close(fd);
}
TEST_F(ProtectedGeneration, RejectsSymlinkSelectorAndDigestMismatch) {
  QFile::remove(base + "/current");
  ASSERT_TRUE(QFile::link(base + "/generations/" + QString::fromLatin1(first) + "/manifest.json", base + "/current"));
  RuntimeOwner owner(base);
  EXPECT_FALSE(owner.acquire());
  QFile::remove(base + "/current");
  select(first);
  write(base + "/generations/" + QString::fromLatin1(first) + "/manifest.json", "{}");
  EXPECT_FALSE(owner.refresh());
}
TEST_F(ProtectedGeneration, CleanupFailureDisablesOwnerPermanentlyAcrossRefresh) {
  RuntimeOwner owner(base);
  auto active = owner.acquire();
  ASSERT_TRUE(active);
  GenerationAccess::disable(active);
  EXPECT_FALSE(GenerationAccess::launchAllowed(active));
  EXPECT_FALSE(owner.acquire());
  select(create("second"));
  EXPECT_FALSE(owner.refresh());
  EXPECT_FALSE(owner.acquire());
}
TEST_F(ProtectedGeneration, LegacyAndSessionCapabilitiesAreValidatedPerSelection) {
  RuntimeOwner owner(base);
  ASSERT_TRUE(owner.acquire());
  EXPECT_FALSE(owner.acquire().supportsSessions());
  const auto modern = create("modern", 1);
  select(modern);
  ASSERT_TRUE(owner.refresh()) << owner.diagnostic().toStdString();
  EXPECT_TRUE(owner.acquire().supportsSessions());
  const auto invalid = create("future", 2);
  select(invalid);
  EXPECT_FALSE(owner.refresh());
  EXPECT_FALSE(owner.acquire());
}
}  // namespace
