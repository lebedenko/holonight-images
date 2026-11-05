// SPDX-License-Identifier: GPL-3.0-or-later
// Deliberately standalone: no production backend or installed API changes.
#include "../../tests/exif_fixture.h"

#include <QColorSpace>
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

#include <glycin.h>
#include <iostream>
#include <limits>
#include <sys/resource.h>

namespace {
bool write(const QString& path, const QByteArray& data) {
  QFile file(path);
  return file.open(QIODevice::WriteOnly) && file.write(data) == data.size();
}

bool fixtures(const QString& root) {
  if (!QDir().mkpath(root + "/links")) return false;
  QImage image(64, 32, QImage::Format_RGBA8888);
  image.fill(QColor(200, 100, 50, 128));
  image.setText("Thumb::URI", "file:///feasibility/source.png");
  image.setText("Thumb::MTime", "1234");
  image.setColorSpace(QColorSpace::SRgb);
  if (!image.save(root + "/alpha.png")) return false;
  image = QImage(2048, 1024, QImage::Format_RGB32);
  image.fill(QColor(20, 80, 160));
  if (!image.save(root + "/large.png") || !image.save(root + "/plain.jpg") || !image.save(root + "/plain.bmp"))
    return false;
  if (!write(root + "/exif.jpg", ExifFixture::jpegWithApp1(ExifFixture::sonyPayload()))) return false;
  const auto oriented = QByteArray("Exif\0\0", 6) + ExifFixture::tiff({ExifFixture::shortValue(0x0112, 6)}, {}, {});
  if (!write(root + "/orientation.jpg", ExifFixture::jpegWithApp1(oriented))) return false;
  const QByteArray svg =
      "<svg xmlns=\"http://www.w3.org/2000/svg\" xmlns:xlink=\"http://www.w3.org/1999/xlink\" width=\"64\" "
      "height=\"32\">"
      "<image xlink:href=\"%1\" width=\"64\" height=\"32\"/></svg>";
  if (!write(root + "/links/local.svg", QByteArray(svg).replace("%1", "child.png")) ||
      !write(root + "/links/parent.svg", QByteArray(svg).replace("%1", "../alpha.png")) ||
      !write(root + "/links/symlink.svg", QByteArray(svg).replace("%1", "escape.png")) ||
      !write(root + "/static.svg",
             "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"32\">"
             "<rect width=\"64\" height=\"32\" fill=\"red\"/></svg>"))
    return false;
  QFile source(root + "/alpha.png");
  if (!source.open(QIODevice::ReadOnly)) return false;
  const auto png = source.readAll();
  return write(root + "/links/child.png", png) &&
         write(root + "/embedded.svg", QByteArray(svg).replace("%1", "data:image/png;base64," + png.toBase64()));
}

struct Pending {
  GMainLoop* loop;
  GlyImage* image = nullptr;
  GError* error = nullptr;
};

void loaded(GObject* source, GAsyncResult* result, gpointer data) {
  auto* pending = static_cast<Pending*>(data);
  pending->image = gly_loader_load_finish(GLY_LOADER(source), result, &pending->error);
  g_main_loop_quit(pending->loop);
}
}  // namespace

int main(int argc, char** argv) {
  QCoreApplication app(argc, argv);
  const auto args = app.arguments();
  if (args.size() == 3 && args[1] == "fixtures") return fixtures(args[2]) ? 0 : 1;
  if (args.size() < 3) return 2;
  const auto mode = args[1];
  QFile source(args[2]);
  if (!source.open(QIODevice::ReadOnly) || source.size() > 16 * 1024 * 1024) return 2;
  const auto encoded = source.readAll();
  QJsonObject output{{"mode", mode}, {"file", args[2]}, {"encoded_bytes", encoded.size()}};
  QElapsedTimer timer;
  timer.start();
  if (mode == "qt") {
    QBuffer buffer;
    buffer.setData(encoded);
    buffer.open(QIODevice::ReadOnly);
    QImageReader reader(&buffer);
    reader.setAutoTransform(true);
    const auto image = reader.read();
    output["ok"] = !image.isNull();
    output["width"] = image.width();
    output["height"] = image.height();
    output["elapsed_us"] = timer.nsecsElapsed() / 1000;
  } else {
    if (g_getenv("GLYCIN_DISABLE_SANDBOX")) {
      std::cerr << "Refusing GLYCIN_DISABLE_SANDBOX override\n";
      return 2;
    }
    g_autoptr(GBytes) bytes = g_bytes_new(encoded.constData(), encoded.size());
    g_autoptr(GInputStream) stream = g_memory_input_stream_new_from_bytes(bytes);
    g_autoptr(GFile) file = g_file_new_for_path(args[2].toUtf8().constData());
    // Path mode is diagnostic only. Stream/bytes never reveal a source pathname.
    g_autoptr(GlyLoader) loader = mode == "path"    ? gly_loader_new(file)
                                  : mode == "bytes" ? gly_loader_new_for_bytes(bytes)
                                                    : gly_loader_new_for_stream(stream);
    gly_loader_set_sandbox_selector(loader, GLY_SANDBOX_SELECTOR_BWRAP);
    gly_loader_set_accepted_memory_formats(loader, GLY_MEMORY_SELECTION_R8G8B8A8_PREMULTIPLIED);
    gly_loader_set_color_convert_icc_srgb(loader, TRUE);
    gly_loader_set_apply_transformations(loader, mode != "ignore");
    g_autoptr(GError) error = nullptr;
    g_autoptr(GlyImage) image = nullptr;
    if (mode == "cancel" || mode == "cancel-running") {
      g_autoptr(GCancellable) cancel = g_cancellable_new();
      // A private context, as needed by synchronous provider callers on worker threads.
      GMainContext* context = g_main_context_new();
      g_main_context_push_thread_default(context);
      GMainLoop* loop = g_main_loop_new(context, FALSE);
      Pending pending{loop};
      GSource* cancellation = g_timeout_source_new(1);
      g_source_set_callback(
          cancellation,
          [](gpointer data) -> gboolean {
            g_cancellable_cancel(G_CANCELLABLE(data));
            return G_SOURCE_REMOVE;
          },
          cancel, nullptr);
      if (mode == "cancel")
        g_cancellable_cancel(cancel);
      else
        g_source_attach(cancellation, context);
      gly_loader_load_async(loader, cancel, loaded, &pending);
      g_main_loop_run(loop);
      image = pending.image;
      error = pending.error;
      g_source_destroy(cancellation);
      g_source_unref(cancellation);
      output["cancelled"] = error && g_error_matches(error, G_IO_ERROR, G_IO_ERROR_CANCELLED);
      g_main_loop_unref(loop);
      g_main_context_pop_thread_default(context);
      g_main_context_unref(context);
    } else {
      image = gly_loader_load(loader, &error);
    }
    output["load_us"] = timer.nsecsElapsed() / 1000;
    if (image) {
      output["mime"] = gly_image_get_mime_type(image);
      output["source_width"] = static_cast<int>(gly_image_get_width(image));
      output["source_height"] = static_cast<int>(gly_image_get_height(image));
      output["orientation"] = gly_image_get_transformation_orientation(image);
      g_auto(GStrv) keys = gly_image_get_metadata_keys(image);
      QJsonObject metadata;
      for (auto key = keys; key && *key; ++key) {
        g_autofree gchar* value = gly_image_get_metadata_key_value(image, *key);
        metadata[*key] = value ? value : "";
      }
      output["metadata"] = metadata;
      g_autoptr(GlyFrameRequest) request = gly_frame_request_new();
      gly_frame_request_set_scale(request, 32, 32);
      gly_frame_request_set_loop_animation(request, FALSE);
      g_autoptr(GlyFrame) frame = gly_image_get_specific_frame(image, request, &error);
      if (frame) {
        const auto width = gly_frame_get_width(frame);
        const auto height = gly_frame_get_height(frame);
        const auto stride = gly_frame_get_stride(frame);
        GBytes* pixels = gly_frame_get_buf_bytes(frame);
        const auto length = g_bytes_get_size(pixels);
        const auto format = gly_frame_get_memory_format(frame);
        const bool valid = width > 0 && height > 0 && width <= 32768 && height <= 32768 &&
                           stride >= uint64_t(width) * 4 && uint64_t(stride) * height <= length &&
                           length <= 64 * 1024 * 1024 && stride <= std::numeric_limits<int>::max() &&
                           format == GLY_MEMORY_R8G8B8A8_PREMULTIPLIED;
        output["ok"] = valid;
        output["width"] = static_cast<int>(width);
        output["height"] = static_cast<int>(height);
        output["stride"] = static_cast<int>(stride);
        output["pixel_bytes"] = static_cast<qint64>(length);
        output["color_mode"] = gly_frame_get_color_mode(frame);
        output["delay_us"] = static_cast<qint64>(gly_frame_get_delay(frame));
        if (mode == "frames") {
          QJsonArray delays{static_cast<qint64>(gly_frame_get_delay(frame))};
          for (int i = 0; i < 3; ++i) {
            g_autoptr(GlyFrame) next = gly_image_get_specific_frame(image, request, &error);
            if (!next) break;
            delays.append(static_cast<qint64>(gly_frame_get_delay(next)));
          }
          output["frame_delays_us"] = delays;
          output["end_of_animation"] =
              error && g_error_matches(error, GLY_LOADER_ERROR, GLY_LOADER_ERROR_NO_MORE_FRAMES);
          if (output["end_of_animation"].toBool()) g_clear_error(&error);
        }
        if (valid) {
          QElapsedTimer copyTimer;
          copyTimer.start();
          const QImage borrowed(static_cast<const uchar*>(g_bytes_get_data(pixels, nullptr)), width, height, stride,
                                QImage::Format_RGBA8888_Premultiplied);
          const auto owned = borrowed.copy();
          output["copy_us"] = copyTimer.nsecsElapsed() / 1000;
          output["pixel_rgba"] = QString::number(owned.pixelColor(0, 0).rgba(), 16);
        }
      }
    }
    output["elapsed_us"] = timer.nsecsElapsed() / 1000;
    output["caller_file_open"] = source.isOpen();
    output["stream_closed"] = bool(g_input_stream_is_closed(stream));
    if (error) {
      output["ok"] = false;
      output["error"] = error->message;
      output["error_domain"] = g_quark_to_string(error->domain);
      output["error_code"] = error->code;
    }
  }
  rusage usage{};
  if (getrusage(RUSAGE_SELF, &usage) == 0) {
    output["application_peak_rss_kib"] = static_cast<qint64>(usage.ru_maxrss);
    output["application_cpu_us"] = static_cast<qint64>(usage.ru_utime.tv_sec + usage.ru_stime.tv_sec) * 1000000 +
                                   usage.ru_utime.tv_usec + usage.ru_stime.tv_usec;
  }
  std::cout << QJsonDocument(output).toJson(QJsonDocument::Compact).constData() << '\n';
  return output["ok"].toBool() || output["cancelled"].toBool() ? 0 : 1;
}
