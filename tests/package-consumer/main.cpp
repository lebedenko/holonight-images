#include <QBuffer>
#include <QCoreApplication>

#include <holonight_images/image.h>
int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  QImage image(4, 2, QImage::Format_ARGB32);
  image.fill(Qt::red);
  QByteArray bytes;
  QBuffer device(&bytes);
  device.open(QIODevice::ReadWrite);
  if (!image.save(&device, "PNG")) return 1;
  const std::atomic_bool cancelled{false};
  const HolonightImages::Limits limits{1048576, 1000, 100, 1048576, 1024, 1024, 100};
  const auto result = HolonightImages::decode(device, {.limits = limits, .bound = {2, 2}}, cancelled);
  return result.outcome == HolonightImages::Outcome::Success && result.image.size() == QSize(2, 1) ? 0 : 1;
}
