// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QStringList>

namespace HolonightImages::Isolation {
// Fully validate the bundle on every call; return only verified read-only binds.
QStringList verifyRuntime(const QString& root);
// Additional eligibility check for validation reuse. Includes every ancestor up
// to /; mutable development prefixes must continue using verifyRuntime per call.
void verifyProtectedRuntime(const QString& root);
}  // namespace HolonightImages::Isolation
