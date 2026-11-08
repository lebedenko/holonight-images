// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QJsonObject>

#include <holonight_images/isolated.h>
#include <stdexcept>

namespace HolonightImages::Isolation {
constexpr qint64 byteCeiling = 256LL * 1024 * 1024;
constexpr qint64 controlCeiling = 65536;
struct ProtocolError : std::runtime_error {
  using std::runtime_error::runtime_error;
};
enum class Operation : unsigned char { Inspect, Metadata, Decode };
struct Request {
  Operation operation = Operation::Inspect;
  DecodeOptions options;
  bool metadata{};
};
struct Reply {
  Inspection inspection;
  MetadataResult metadata;
  DecodeResult decoded;
};
QJsonObject requestControl(const Request& request, qint64 bytes);
Request parseRequest(const QJsonObject& record, qint64& bytes);
QJsonObject replyControl(Reply& reply, Operation operation, QByteArray& pixels);
Reply parseReply(const QJsonObject& record, const QByteArray& pixels, const Request& request);
qint64 integer(const QJsonObject& record, const char* key, qint64 low, qint64 high);
QJsonObject parseControl(const QByteArray& bytes);
QByteArray frame(const QJsonObject& record);
int pixelDepth(int format);
}  // namespace HolonightImages::Isolation
