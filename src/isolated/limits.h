// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QtTypes>

#include <limits>

namespace HolonightImages::Isolation {
constexpr qint64 bytesPerMiB = 1024LL * 1024;
constexpr qint64 byteCeiling = 256 * bytesPerMiB;
constexpr qint64 inputCeiling = byteCeiling;
constexpr qint64 qtAllocationCeiling = 256 * bytesPerMiB;
constexpr qint64 scopeMemoryCeiling = 2LL * 1024 * bytesPerMiB;
constexpr qint64 scopeSwapCeiling = 0;
static_assert(qtAllocationCeiling % bytesPerMiB == 0);
static_assert(qtAllocationCeiling / bytesPerMiB <= std::numeric_limits<int>::max());
constexpr int qtAllocationMiB = static_cast<int>(qtAllocationCeiling / bytesPerMiB);
static_assert(qtAllocationMiB * bytesPerMiB == qtAllocationCeiling);
static_assert(byteCeiling == qtAllocationCeiling);
}  // namespace HolonightImages::Isolation
