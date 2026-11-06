// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "source-capture.h"

#include <QFile>
#include <QMap>
#include <QStringList>

#include <functional>
#include <sys/stat.h>

namespace Comparison {
// Private caller adapter. The provider and capture() never resolve names.
class LinkedAcquisition {
 public:
  LinkedAcquisition(int base, int main, QString mainName);
  ~LinkedAcquisition();
  LinkedAcquisition(const LinkedAcquisition&) = delete;
  LinkedAcquisition& operator=(const LinkedAcquisition&) = delete;
  CaptureResult captureMain(const std::atomic_bool& cancelled);
  CaptureOutcome complete(const QStringList& paths, const std::atomic_bool& cancelled,
                          const std::function<void()>& beforeRevalidation = {});
  const QMap<QString, QByteArray>& files() const { return published_; }
  const QMap<QString, struct stat>& identities() const { return identities_; }

 private:
  int base_;
  int main_;
  QString mainName_;
  QByteArray mainBytes_;
  struct stat mainIdentity_{};
  bool ready_ = false;
  QMap<QString, QByteArray> published_;
  QMap<QString, struct stat> identities_;
};
bool validResourcePaths(const QStringList& paths);
}  // namespace Comparison
