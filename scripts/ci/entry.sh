#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
set -euo pipefail
export HOME=/work/home XDG_RUNTIME_DIR=/work/runtime LC_ALL=C.UTF-8 TZ=UTC
export XDG_CONFIG_HOME=/work/config XDG_DATA_HOME=/work/data XDG_CACHE_HOME=/work/cache
export CC=clang CXX=clang++ CMAKE_BUILD_PARALLEL_LEVEL=${JOBS:-2}
export QT_QPA_PLATFORM=offscreen QSG_RHI_BACKEND=software QT_QUICK_BACKEND=software
export QT_QPA_PLATFORMTHEME= QT_STYLE_OVERRIDE=
# This fresh, offline container exposes only the selected sources and disposable prefix.
# Shell still creates its private bus/config; it does not need another host-hiding namespace.
export UQC_ISOLATED=1
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_CACHE_HOME"
chmod 700 "$HOME" "$XDG_RUNTIME_DIR"
printf 'Acceptance image: %s\n' "$HOLONIGHT_CI_IMAGE"
for tool in clang clang++ clang-format clang-tidy cmake ninja reuse git task; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
  "$tool" --version
 done
pkg-config --modversion Qt6Core
export QMLFORMAT=/usr/lib/qt6/bin/qmlformat
if [[ "$1" == format ]]; then
  python3 scripts/quality.py format
  exit
fi
export CMAKE_PREFIX_PATH="$PWD/build/deps/prefix"
export QML_IMPORT_PATH="$CMAKE_PREFIX_PATH/lib/qt6/qml"
export LD_LIBRARY_PATH="$CMAKE_PREFIX_PATH/lib"
python3 scripts/ci/providers.py
bash scripts/ci/check.sh
if [[ "$1" == integration ]]; then
  bash scripts/ci/integration.sh
fi
