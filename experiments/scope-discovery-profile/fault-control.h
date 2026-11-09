// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <string_view>

namespace Profile {
// Qualification only. Seeing the gate's descendant is not proof that the
// sandbox helper has entered main. Require both complete records before cancel.
inline bool readinessCancellation(std::string_view fault, std::string_view stream) {
  bool helper = false;
  bool descendant = false;
  while (!stream.empty()) {
    const auto end = stream.find('\n');
    if (end == std::string_view::npos) break;
    const auto line = stream.substr(0, end);
    helper |= line.starts_with("LRP1 helper 0 ") && line.find(" H ") != std::string_view::npos;
    descendant |= line.starts_with("LRP1 descendant 0 ") && line.find(" descendant ") != std::string_view::npos;
    stream.remove_prefix(end + 1);
  }
  return helper && (fault == "await" || (fault == "descendant" && descendant));
}
}  // namespace Profile
