// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QStringList>

#include <holonight_images/isolated.h>
namespace HolonightImages {
struct GenerationAccess {
  static bool launchAllowed(const GenerationLease& lease);
  static void disable(const GenerationLease& lease);
  static QStringList binds(const GenerationLease& lease);
};
}  // namespace HolonightImages
