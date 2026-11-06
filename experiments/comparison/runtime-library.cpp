// SPDX-License-Identifier: GPL-3.0-or-later
#include <unistd.h>
#ifdef CONTROL_PRELOAD
__attribute__((constructor)) static void activated() {
  constexpr char token[] = "HN_PRELOAD_ACTIVATED\n";
  (void)write(2, token, sizeof(token) - 1);
}
#elif defined(CONTROL_AUDIT)
extern "C" unsigned int la_version(unsigned int) {
  constexpr char token[] = "HN_AUDIT_ACTIVATED\n";
  (void)write(2, token, sizeof(token) - 1);
  return 2;
}
#else
extern "C" const char* holonight_runtime_control() { return "HN_LIBRARY_ACTIVATED"; }
#endif
