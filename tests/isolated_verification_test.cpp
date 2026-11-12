// SPDX-License-Identifier: GPL-3.0-or-later
#include "../src/isolated/protocol.h"
#include "../src/isolated/verification.h"

#include <QCryptographicHash>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QTemporaryDir>

#include <gtest/gtest.h>
#include <sys/stat.h>

using namespace HolonightImages::Isolation;
namespace {
class RuntimeVerification : public testing::Test {
 protected:
  QTemporaryDir directory;
  QJsonArray files;

  void add(const QString& path, const QByteArray& bytes = {}) {
    const auto target = directory.path() + "/" + path;
    ASSERT_TRUE(QDir().mkpath(QFileInfo(target).path()));
    QFile file(target);
    ASSERT_TRUE(file.open(QIODevice::WriteOnly));
    ASSERT_EQ(file.write(bytes), bytes.size());
    file.close();
    ASSERT_EQ(chmod(QFile::encodeName(target).constData(), 0644), 0);
    files.append(QJsonObject{
        {"path", path},
        {"mode", 0644},
        {"size", bytes.size()},
        {"sha256", QString::fromLatin1(QCryptographicHash::hash(bytes, QCryptographicHash::Sha256).toHex())}});
  }
  void manifest() {
    QFile file(directory.path() + "/manifest.json");
    ASSERT_TRUE(file.open(QIODevice::WriteOnly));
    const auto bytes = QJsonDocument(QJsonObject{{"version", 1}, {"files", files}}).toJson();
    ASSERT_EQ(file.write(bytes), bytes.size());
    file.close();
    ASSERT_EQ(chmod(QFile::encodeName(file.fileName()).constData(), 0644), 0);
  }
  void SetUp() override {
    ASSERT_TRUE(directory.isValid());
    for (const auto* path :
         {"usr/libexec/holonight-images-helper", "usr/lib/qt6/plugins/imageformats/libqgif.so",
          "usr/lib/qt6/plugins/imageformats/libqjpeg.so", "usr/lib/qt6/plugins/imageformats/libqtiff.so",
          "usr/lib/qt6/plugins/imageformats/libqwebp.so"}) {
      add(path);
    }
    manifest();
  }
};
TEST_F(RuntimeVerification, CountsManifestTowardFileLimit) {
  while (files.size() < 127) {
    add(QString("usr/lib/fixture-%1").arg(files.size()));
  }
  manifest();
  EXPECT_NO_THROW(verifyRuntime(directory.path()));
  add("usr/lib/one-too-many");
  manifest();
  EXPECT_THROW(verifyRuntime(directory.path()), ProtocolError);
}
TEST_F(RuntimeVerification, CountsManifestTowardByteLimitBeforeHashingPayload) {
  const QString path = "usr/lib/large";
  add(path);
  QFile payload(directory.path() + "/" + path);
  ASSERT_TRUE(payload.open(QIODevice::WriteOnly));
  ASSERT_TRUE(payload.resize(128LL * 1024 * 1024));
  payload.close();
  auto record = files.last().toObject();
  record["size"] = 128LL * 1024 * 1024;
  files[files.size() - 1] = record;
  manifest();
  try {
    verifyRuntime(directory.path());
    FAIL() << "oversized generation accepted";
  } catch (const ProtocolError& error) {
    EXPECT_STREQ(error.what(), "runtime aggregate byte limit");
  }
}
TEST_F(RuntimeVerification, MutableDevelopmentPrefixIsNotProtected) {
  EXPECT_NO_THROW(verifyRuntime(directory.path()));
  // Also fails when run as root: /tmp is writable by ordinary users.
  EXPECT_THROW(verifyProtectedRuntime(directory.path()), ProtocolError);
}
TEST_F(RuntimeVerification, RejectsInventorySymlink) {
  const auto path = directory.path() + "/usr/lib/alias";
  ASSERT_TRUE(QFile::link(directory.path() + "/manifest.json", path));
  EXPECT_THROW(verifyRuntime(directory.path()), ProtocolError);
  EXPECT_THROW(verifyProtectedRuntime(directory.path()), ProtocolError);
}
TEST_F(RuntimeVerification, RejectsSymlinkDirectoryInsideInventory) {
  const auto path = directory.path() + "/usr/alias";
  ASSERT_TRUE(QFile::link(directory.path() + "/usr/lib", path));
  EXPECT_THROW(verifyRuntime(directory.path()), ProtocolError);
}
}  // namespace
