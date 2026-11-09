// SPDX-License-Identifier: GPL-3.0-or-later
#include "fault-control.h"

#include <cassert>
#include <string>
int main() {
  const std::string descendant = "LRP1 descendant 0 12 descendant 100 12\n";
  const std::string helper = "LRP1 helper 0 2 H 110 0\n";
  assert(!Profile::readinessCancellation("descendant", descendant));
  assert(!Profile::readinessCancellation("descendant", helper));
  assert(Profile::readinessCancellation("descendant", descendant + helper));
  assert(Profile::readinessCancellation("descendant", helper + descendant));
  assert(!Profile::readinessCancellation("descendant", descendant + helper.substr(0, helper.size() - 1)));
  assert(Profile::readinessCancellation("await", helper));
  assert(!Profile::readinessCancellation("await", descendant));
  assert(!Profile::readinessCancellation("timeout", descendant + helper));
  assert(!Profile::readinessCancellation("measure", descendant + helper));
}
