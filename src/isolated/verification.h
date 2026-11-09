// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QStringList>

namespace HolonightImages::Isolation {
// Fully validate the bundle on every call; return only verified read-only binds.
QStringList verifyRuntime(const QString& root);
}  // namespace HolonightImages::Isolation
