// SPDX-License-Identifier: GPL-3.0-or-later
#include "runtime.h"
#include "telemetry.h"

#include <QBuffer>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QJsonDocument>

#include <cstdio>

using namespace HolonightImages;
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  if (argc != 7) return 2;
  Profile::fault = QString::fromLocal8Bit(argv[4]);
  Profile::qualification = Profile::fault != "measure" && Profile::fault != "success";
  Profile::journal = QString::fromLocal8Bit(argv[5]);
  QFile source(QString::fromLocal8Bit(argv[2]));
  if (!source.open(QIODevice::ReadOnly)) return 3;
  std::atomic_bool cancelled{false};
  Profile::cancellation = &cancelled;
  Profile::clockInfo();
  const QString kind = QString::fromLocal8Bit(argv[3]);
  Limits limits{256LL * 1024 * 1024, 64000000, 32768, 256LL * 1024 * 1024, 1024 * 1024, 64LL * 1024 * 1024, 4096};
  if (kind == "cached")
    limits = {32LL * 1024 * 1024, 256 * 256, 256, 32LL * 1024 * 1024, 1024 * 1024, 1024 * 1024, 4096};
  DecodeOptions options{limits, {256, 256}, kind == "cached" ? OrientationPolicy::Ignore : OrientationPolicy::Apply};
  IsolatedClient client(QString::fromLocal8Bit(argv[1]));
  QJsonObject output;
  Inspection facts;
  bool present = false;
  RuntimeStatus status;
  QString diagnostic;
  if (kind == "inspection") {
    auto result = client.inspect(source, limits, cancelled, OrientationPolicy::Apply, false);
    status = result.runtime;
    diagnostic = result.diagnostic;
    present = result.result.has_value();
    if (present) facts = *result.result;
  } else {
    auto result = client.decode(source, options, cancelled);
    status = result.runtime;
    diagnostic = result.diagnostic;
    present = result.result.has_value();
    if (present) {
      facts = result.result->inspection;
      auto pixels = result.result->image.convertToFormat(QImage::Format_RGBA8888);
      output["decode_outcome"] = int(result.result->outcome);
      output["width"] = pixels.width();
      output["height"] = pixels.height();
      QCryptographicHash hash(QCryptographicHash::Sha256);
      for (int y = 0; y < pixels.height(); ++y)
        hash.addData(QByteArrayView(reinterpret_cast<const char*>(pixels.constScanLine(y)), pixels.width() * 4));
      output["pixels_sha256"] = QString::fromLatin1(hash.result().toHex());
    }
  }
  output["status"] = int(status);
  output["diagnostic"] = diagnostic;
  output["present"] = present;
  if (present) {
    output["outcome"] = int(facts.outcome);
    output["format"] = QString::fromLatin1(facts.format);
    output["source_width"] = facts.sourceSize.width();
    output["source_height"] = facts.sourceSize.height();
    output["oriented_width"] = facts.orientedSize.width();
    output["oriented_height"] = facts.orientedSize.height();
    output["orientation"] = int(facts.orientation);
    output["metadata_empty"] = facts.metadata.facts == ExifFacts{};
  }
  output["events"] = Profile::json();
  output["version"] = 1;
  output["queries"] = Profile::queries;
  output["waits"] = Profile::waits;
  output["unknown"] = Profile::unknown;
  output["capture_failed"] = Profile::failed;
  output["stderr_base64"] = QString::fromLatin1(Profile::errors.toBase64());
  output["cleanup"] = QJsonDocument::fromJson(Profile::cleanupJson.toUtf8()).object();
  QFile target(QString::fromLocal8Bit(argv[6]));
  const auto bytes = QJsonDocument(output).toJson();
  if (!target.open(QIODevice::WriteOnly) || target.write(bytes) != bytes.size() || !target.flush()) return 4;
  return 0;
}
