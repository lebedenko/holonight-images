#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
task test
task format-check
cmake -S . -B build/dev/fuzz -G Ninja -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF -DHOLONIGHT_IMAGES_FUZZING=ON -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build/dev/fuzz
task tidy
reuse lint
