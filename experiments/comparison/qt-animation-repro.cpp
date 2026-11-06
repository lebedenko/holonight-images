// SPDX-License-Identifier: GPL-3.0-or-later
#include <QBuffer>
#include <QCoreApplication>
#include <QImageReader>
#include <QJsonDocument>
#include <QJsonObject>
#include <QtEndian>

#include <cstdio>
#include <memory>

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  QImageReader::setAllocationLimit(256);
  QByteArray snapshot;
  QBuffer buffer(&snapshot);
  std::unique_ptr<QImageReader> reader;
  for (;;) {
    quint32 length;
    if (std::fread(&length, 1, 4, stdin) != 4) return 2;
    length = qFromBigEndian(length);
    if (!length || length > 65536) return 2;
    QByteArray json(length, Qt::Uninitialized);
    if (std::fread(json.data(), 1, length, stdin) != length) return 2;
    const auto request = QJsonDocument::fromJson(json).object();
    const auto size = request.value("bytes").toInteger(-1);
    if (size < 0 || size > 256LL * 1024 * 1024) return 2;
    QByteArray data(size, Qt::Uninitialized);
    if (std::fread(data.data(), 1, size_t(size), stdin) != size_t(size)) return 2;
    const auto op = request.value("op").toString();
    QJsonObject result;
    QImage image;
    if (op == "load" || op == "restart") {
      reader.reset();
      buffer.close();
      if (op == "load") snapshot = data;
      buffer.open(QIODevice::ReadOnly);
      reader = std::make_unique<QImageReader>(&buffer, "gif");
      result = {{"outcome", "loaded"}, {"frame_count", reader->imageCount()}};
    } else if (op == "frame" && reader) {
      image = reader->read();
      result = {{"outcome", image.isNull() ? "end" : "success"},
                {"delay_ms", reader->nextImageDelay()},
                {"error_code", int(reader->error())},
                {"error", reader->errorString()}};
      image.convertTo(QImage::Format_RGBA8888_Premultiplied);
      if (image.sizeInBytes() > 256LL * 1024 * 1024) return 2;
    } else
      result = {{"outcome", op == "close" ? "closed" : "unsupported"}};
    result["bytes"] = image.sizeInBytes();
    result["width"] = image.width();
    result["height"] = image.height();
    result["stride"] = image.bytesPerLine();
    json = QJsonDocument(result).toJson(QJsonDocument::Compact);
    length = qToBigEndian(quint32(json.size()));
    std::fwrite(&length, 1, 4, stdout);
    std::fwrite(json.data(), 1, size_t(json.size()), stdout);
    if (!image.isNull()) std::fwrite(image.constBits(), 1, size_t(image.sizeInBytes()), stdout);
    std::fflush(stdout);
    if (op == "close") return 0;
  }
}
