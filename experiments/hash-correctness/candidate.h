// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QCryptographicHash>
#include <QIODevice>
#include <array>

namespace HashCorrectness {
inline bool addData(QCryptographicHash& hash, QIODevice* device) {
  if (!device->isOpen() || !device->isReadable())
    return false;
  std::array<char, 65536> buffer;
  qint64 count;
  while ((count = device->read(buffer.data(), buffer.size())) > 0)
    hash.addData(QByteArrayView(buffer.data(), count));
  return device->atEnd();
}
}
