#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
# Container runtimes are acceptance artifacts only; namespace/cgroup operations
# are independently exercised by the explicit host runtime suite.
cmake --preset dev -DHOLONIGHT_IMAGES_ISOLATED=ON
cmake --build --preset dev
python3 scripts/prepare-isolated-runtime.py --helper build/dev/holonight-images-helper \
  --plugins /usr/lib/qt6/plugins --output build/dev/acceptance-runtime
cmake --preset dev -DHOLONIGHT_IMAGES_RUNTIME_BUNDLE="$PWD/build/dev/acceptance-runtime"
task test
task format-check
cmake -S . -B build/dev/fuzz -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF -DHOLONIGHT_IMAGES_FUZZING=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build/dev/fuzz
task tidy
reuse lint
