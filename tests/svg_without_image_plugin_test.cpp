#include <QCoreApplication>
#include <QImageReader>
#include <QTemporaryDir>

#include <holonight_images/svg.h>

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  QTemporaryDir empty;
  if (!empty.isValid()) return 1;
  QCoreApplication::setLibraryPaths({empty.path()});
  if (QImageReader::supportedImageFormats().contains("svg")) return 2;
  const std::atomic_bool cancelled{false};
  const auto result = HolonightImages::rasterizeSvg(
      "<svg xmlns='http://www.w3.org/2000/svg' width='24' height='24'>"
      "<rect width='12' height='12' fill='red'/></svg>",
      {.bound = {240, 240}, .outputBytes = 240 * 240 * 4}, cancelled);
  if (result.inspection.outcome != HolonightImages::Outcome::Success || result.image.size() != QSize(240, 240))
    return 3;
  if (result.image.pixelColor(20, 20) != QColor(Qt::red) || result.image.pixelColor(200, 200).alpha() != 0) return 4;
  return 0;
}
