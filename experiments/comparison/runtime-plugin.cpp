// SPDX-License-Identifier: GPL-3.0-or-later
#include <QIODevice>
#include <QImage>
#include <QImageIOHandler>
#include <QImageIOPlugin>
class ControlHandler final : public QImageIOHandler {
 public:
  bool canRead() const override { return device() && device()->peek(9) == "HNCONTROL"; }
  bool read(QImage* image) override {
    if (!canRead()) return false;
    *image = QImage(1, 1, QImage::Format_RGBA8888);
    image->fill(QColor(31, 79, 127, 255));
    return true;
  }
};
class ControlPlugin final : public QImageIOPlugin {
  Q_OBJECT
  Q_PLUGIN_METADATA(IID "org.qt-project.Qt.QImageIOHandlerFactoryInterface" FILE "runtime-plugin.json")
 public:
  Capabilities capabilities(QIODevice* device, const QByteArray& format) const override {
    return format == "hncontrol" || (device && device->peek(9) == "HNCONTROL") ? CanRead : Capabilities{};
  }
  QImageIOHandler* create(QIODevice* device, const QByteArray& format) const override {
    auto* handler = new ControlHandler;
    handler->setDevice(device);
    handler->setFormat(format);
    return handler;
  }
};
#include "runtime-plugin.moc"
