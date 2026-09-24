#include <QBuffer>

#include <gtest/gtest.h>
#include <holonight_images/svg.h>
#include <limits>

using namespace HolonightImages;
namespace {
const std::atomic_bool running{false};
QByteArray document(QByteArray attributes = "width='24' height='24'", QByteArray body = {}) {
  return "<svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' " + attributes + ">" +
         body + "</svg>";
}
SvgRenderResult render(QByteArray bytes, QSize bound = {240, 240}, qint64 limit = 1024 * 1024) {
  return rasterizeSvg(bytes, {.bound = bound, .outputBytes = limit}, running);
}
class Source : public QBuffer {
 public:
  explicit Source(QByteArray* bytes) : QBuffer(bytes) { open(ReadOnly | Unbuffered); }
  bool failRead = false;
  bool failSeek = false;
  bool sequential = false;
  bool underreport = false;
  std::atomic_bool* cancelOnRead = nullptr;
  qint64 size() const override { return underreport ? 1 : QBuffer::size(); }
  bool isSequential() const override { return sequential; }
  bool seek(qint64 offset) override { return !failSeek && QBuffer::seek(offset); }

 protected:
  qint64 readData(char* data, qint64 count) override {
    if (failRead) return -1;
    const auto result = QBuffer::readData(data, count);
    if (cancelOnRead) cancelOnRead->store(true);
    return result;
  }
};
}  // namespace

TEST(Svg, DefaultSizeTakesPrecedenceOverViewBox) {
  const auto result = inspectSvg(document("width='80' height='40' viewBox='0 0 10 30'"), running);
  ASSERT_EQ(result.outcome, Outcome::Success);
  EXPECT_EQ(result.facts.defaultSize, QSizeF(80, 40));
  EXPECT_EQ(result.facts.viewBox, QRectF(0, 0, 10, 30));
  EXPECT_EQ(result.facts.documentSize, QSizeF(80, 40));
  EXPECT_EQ(render(document("width='80' height='40' viewBox='0 0 10 30'")).image.size(), QSize(240, 120));
}
TEST(Svg, FractionalDimensionsSurviveUntilPixelCalculation) {
  for (const auto& attributes :
       {"viewBox='1 2 0.25 0.5'", "width='0.25' height='0.5'", "width='0.25px' height='0.5px' viewBox='0 0 10 10'"}) {
    const auto result = inspectSvg(document(attributes), running);
    ASSERT_EQ(result.outcome, Outcome::Success) << attributes;
    EXPECT_EQ(result.facts.documentSize, QSizeF(0.25, 0.5));
    EXPECT_EQ(render(document(attributes)).image.size(), QSize(120, 240));
  }
  EXPECT_EQ(svgPixelSize({24, 24}, {301, 301}), QSize(301, 301));
  EXPECT_EQ(svgPixelSize({7.5, 3.5}, {101, 101}), QSize(101, 47));
}
TEST(Svg, DimensionFallbackRequiresFinitePositiveGeometry) {
  EXPECT_EQ(svgDocumentSize({80, 40}, {0, 0, 10, 30}), QSizeF(80, 40));
  EXPECT_EQ(svgDocumentSize({}, {0, 0, 0.25, 0.5}), QSizeF(0.25, 0.5));
  EXPECT_TRUE(svgDocumentSize({}, {0, 0, -1, 4}).isEmpty());
  EXPECT_TRUE(svgDocumentSize({}, {0, 0, std::numeric_limits<double>::infinity(), 4}).isEmpty());
  EXPECT_TRUE(svgDocumentSize({}, {std::numeric_limits<double>::quiet_NaN(), 0, 4, 4}).isEmpty());
  EXPECT_EQ(inspectSvg(document("width='0' height='0'"), running).outcome, Outcome::Damaged);
  EXPECT_EQ(inspectSvg(document({}), running).outcome, Outcome::Damaged);
}
TEST(Svg, EnlargementPreservesTransparency) {
  const auto result = render(document("width='24' height='24'", "<rect width='12' height='12' fill='red'/>"));
  ASSERT_EQ(result.inspection.outcome, Outcome::Success);
  ASSERT_EQ(result.image.size(), QSize(240, 240));
  EXPECT_EQ(result.image.pixelColor(20, 20), QColor(Qt::red));
  EXPECT_EQ(result.image.pixelColor(200, 200).alpha(), 0);
}
TEST(Svg, OutputBudgetAppliesBeforeAllocationWithoutLogicalPixelLimits) {
  const auto huge = document("width='1000000' height='2000000'");
  EXPECT_EQ(render(huge, {20, 20}, 800).inspection.outcome, Outcome::Success);
  const auto limited = render(huge, {20, 20}, 799);
  EXPECT_EQ(limited.inspection.outcome, Outcome::ResourceLimit);
  EXPECT_TRUE(limited.image.isNull());
  for (const auto size : {QSize{}, QSize(0, 5), QSize(-1, 8)})
    EXPECT_EQ(render(document(), size).inspection.outcome, Outcome::ResourceLimit);
  EXPECT_EQ(render(document(), {1, 1}, 0).inspection.outcome, Outcome::ResourceLimit);
  EXPECT_EQ(render(document(), {INT_MAX, INT_MAX}, 1024).inspection.outcome, Outcome::ResourceLimit);
}
TEST(Svg, MalformedXmlAndCompressedInputAreNotRendered) {
  for (const auto& bytes : {QByteArray(), QByteArray("<svg>"), QByteArray("<html/>"), document({}, "<rect></path>"),
                            QByteArray("\x1f\x8b\x08", 3), document({}, "<image href='relative.png'>")}) {
    const auto result = render(bytes);
    EXPECT_EQ(result.inspection.outcome, Outcome::Damaged);
    EXPECT_TRUE(result.image.isNull());
  }
}
TEST(Svg, LoadsRetainedBytesFromOffsetZeroAndLeavesDeviceOpen) {
  auto bytes = document();
  Source source(&bytes);
  ASSERT_TRUE(source.seek(5));
  const auto result = loadSvg(source, bytes.size(), running);
  EXPECT_EQ(result.outcome, Outcome::Success);
  EXPECT_EQ(result.bytes, bytes);
  EXPECT_TRUE(source.isOpen());
  bytes = "replacement";
  EXPECT_EQ(inspectSvg(result.bytes, running).outcome, Outcome::Success);
}
TEST(Svg, SourceBudgetChecksReportedAndActualBytes) {
  auto bytes = document();
  Source source(&bytes);
  EXPECT_EQ(loadSvg(source, bytes.size() - 1, running).outcome, Outcome::ResourceLimit);
  source.underreport = true;
  EXPECT_EQ(loadSvg(source, bytes.size() - 1, running).outcome, Outcome::ResourceLimit);
  EXPECT_EQ(loadSvg(source, bytes.size(), running).outcome, Outcome::Success);
  EXPECT_EQ(loadSvg(source, 0, running).outcome, Outcome::ResourceLimit);
  EXPECT_EQ(loadSvg(source, std::numeric_limits<qint64>::max(), running).outcome, Outcome::Success);
}
TEST(Svg, ReadSeekAndSequentialFailuresRemainDistinctFromInvalidXml) {
  auto bytes = document();
  Source source(&bytes);
  source.failRead = true;
  EXPECT_EQ(loadSvg(source, 1024, running).outcome, Outcome::IoFailure);
  source.failRead = false;
  source.failSeek = true;
  EXPECT_EQ(loadSvg(source, 1024, running).outcome, Outcome::IoFailure);
  source.failSeek = false;
  source.sequential = true;
  EXPECT_EQ(loadSvg(source, 1024, running).outcome, Outcome::IoFailure);
  source.close();
  EXPECT_EQ(loadSvg(source, 1024, running).outcome, Outcome::IoFailure);
}
TEST(Svg, CancellationReturnsNoPartialBytesOrImage) {
  std::atomic_bool cancelled{true};
  auto bytes = document();
  Source source(&bytes);
  EXPECT_EQ(loadSvg(source, 1024, cancelled).outcome, Outcome::Cancelled);
  EXPECT_EQ(inspectSvg(bytes, cancelled).outcome, Outcome::Cancelled);
  const auto result = rasterizeSvg(bytes, {.bound = {24, 24}, .outputBytes = 4096}, cancelled);
  EXPECT_EQ(result.inspection.outcome, Outcome::Cancelled);
  EXPECT_TRUE(result.image.isNull());
  cancelled.store(false);
  source.cancelOnRead = &cancelled;
  const auto loaded = loadSvg(source, 1024, cancelled);
  EXPECT_EQ(loaded.outcome, Outcome::Cancelled);
  EXPECT_TRUE(loaded.bytes.isEmpty());
}
TEST(Svg, ClassifiesReferencesWithoutResolvingPaths) {
  EXPECT_EQ(classifySvgReference(u"#gradient"), SvgReferenceKind::Fragment);
  EXPECT_EQ(classifySvgReference(u"./picture.png"), SvgReferenceKind::LocalFile);
  EXPECT_EQ(classifySvgReference(u"/picture.png"), SvgReferenceKind::LocalFile);
  EXPECT_EQ(classifySvgReference(u"file:///picture.png"), SvgReferenceKind::LocalFile);
  EXPECT_EQ(classifySvgReference(u"https://example.com/image.png"), SvgReferenceKind::External);
  EXPECT_EQ(classifySvgReference(u"//example.com/image.png"), SvgReferenceKind::External);
  EXPECT_EQ(classifySvgReference(u"file://server/image.png"), SvgReferenceKind::External);
  EXPECT_EQ(classifySvgReference(u"data:image/svg+xml;base64,PHN2Zy8+"), SvgReferenceKind::Invalid);
}
TEST(Svg, AllowsFragmentReferencesInHrefAndCss) {
  const auto bytes = document({},
                              "<defs><rect id='shape' width='24' height='24'/><linearGradient id='paint'>"
                              "<stop stop-color='red'/></linearGradient></defs>"
                              "<style>rect { fill: url( '#paint' ); }</style>"
                              "<use href='#shape'/><use xlink:href='#shape' style='fill:url(#paint)'/>");
  EXPECT_EQ(inspectSvg(bytes, running).outcome, Outcome::Success);
}
TEST(Svg, RejectsResourceReferencesBeforeRendering) {
  const QList<QPair<QByteArray, SvgResourceReason>> cases{
      {"<image href='local.png'/>", SvgResourceReason::LocalImageReference},
      {"<image href='#local.png' width='24' height='24'/>", SvgResourceReason::ExternalReference},
      {"<image href='data:image/png;base64,iVBORw0KGgo='/>", SvgResourceReason::InvalidEmbeddedImage},
      {"<set attributeName='xlink:href' to='external.png'/>", SvgResourceReason::ExternalReference},
      {"<image xlink:href='../local.png'/>", SvgResourceReason::LocalImageReference},
      {"<use href='local.svg#x'/>", SvgResourceReason::ExternalReference},
      {"<image href='https://example.com/a.png'/>", SvgResourceReason::ExternalReference},
      {"<image href='local.png'/><image href='https://example.com/a.png'/>", SvgResourceReason::ExternalReference},
      {"<image href='https://example.com/a.png'/><image href='local.png'/>", SvgResourceReason::ExternalReference},
      {"<rect fill='url(file:///tmp/paint.svg#id)'/>", SvgResourceReason::ExternalReference},
      {"<style>rect { fill: URL(https://example.com/a.svg#x); }</style>", SvgResourceReason::ExternalReference},
      {"<style>@import 'external.css';</style>", SvgResourceReason::Stylesheet},
      {"<style>@im/**/port url(external.css);</style>", SvgResourceReason::Stylesheet},
      {"<style>rect { fill: u\\72l(external.svg); }</style>", SvgResourceReason::UnsupportedCss},
      {"<rect style='fill:u/**/rl(external.svg)'/>", SvgResourceReason::ExternalReference},
      {"<rect style='fill:url(&quot;external.svg&quot;)'/>", SvgResourceReason::ExternalReference},
      {"<image href='data:image/svg+xml;base64,PHN2Zy8+'/>", SvgResourceReason::InvalidEmbeddedImage},
      {"<image href='data:image/png;base64,PHN2Zy8+'/>", SvgResourceReason::InvalidEmbeddedImage},
      {"<g xml:base='file:///tmp/'><image href='#local'/></g>", SvgResourceReason::ExternalReference}};
  for (const auto& [body, reason] : cases) {
    const auto result = render(document("width='24' height='24'", body));
    EXPECT_EQ(result.inspection.outcome, Outcome::Unsupported) << body.constData();
    EXPECT_EQ(result.inspection.resourceReason, reason) << body.constData();
    EXPECT_TRUE(result.image.isNull());
  }
}
TEST(Svg, RejectsExternalStylesheetsAndEntityDeclarations) {
  for (const auto& prefix :
       {"<!DOCTYPE svg [<!ENTITY image 'file:///tmp/a.png'>]>", "<!DOCTYPE svg SYSTEM 'https://example.com/svg.dtd'>",
        "<!DOCTYPE svg [<!ENTITY % e 'x'>]>"}) {
    const auto result = inspectSvg(prefix + document(), running);
    EXPECT_EQ(result.outcome, Outcome::Unsupported);
    EXPECT_EQ(result.resourceReason, SvgResourceReason::EntityDeclaration);
  }
  const auto result = inspectSvg("<?xml-stylesheet href='external.css'?>" + document(), running);
  EXPECT_EQ(result.outcome, Outcome::Unsupported);
  EXPECT_EQ(result.resourceReason, SvgResourceReason::Stylesheet);
}
TEST(Svg, EmbeddedRasterImagesAreAllowedAndRendered) {
  QImage pixel(1, 1, QImage::Format_ARGB32);
  pixel.fill(Qt::red);
  QByteArray png;
  QBuffer output(&png);
  ASSERT_TRUE(output.open(QIODevice::WriteOnly));
  ASSERT_TRUE(pixel.save(&output, "PNG"));
  const auto uri = "data:image/png;base64," + png.toBase64();
  EXPECT_EQ(classifySvgReference(QString::fromLatin1(uri)), SvgReferenceKind::EmbeddedRaster);
  EXPECT_EQ(classifySvgReference(QString::fromLatin1("DATA:" + uri.mid(5))), SvgReferenceKind::Invalid);
  const auto result =
      render(document("width='24' height='24'", "<image width='24' height='24' xlink:href='" + uri + "'/>"));
  ASSERT_EQ(result.inspection.outcome, Outcome::Success);
  EXPECT_EQ(result.image.pixelColor(120, 120), QColor(Qt::red));
}
TEST(Svg, NonResourceAttributeTextIsNotMistakenForCss) {
  EXPECT_EQ(inspectSvg(document("width='24' height='24' id='url'",
                                "<style>.curl {fill:red}</style><rect class='curl' id='curl' width='24' height='24'/>"),
                       running)
                .outcome,
            Outcome::Success);
}
TEST(Svg, StaticRenderingExplicitlyDisablesAnimation) {
  const auto result =
      render(document("width='24' height='24'",
                      "<rect width='24' height='24' fill='red'>"
                      "<animate attributeName='fill' from='blue' to='green' dur='1s' repeatCount='indefinite'/>"
                      "</rect>"));
  ASSERT_EQ(result.inspection.outcome, Outcome::Success);
  EXPECT_EQ(result.image.pixelColor(120, 120), QColor(Qt::red));
}
