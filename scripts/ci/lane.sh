#!/bin/sh
set -eu
test "$1" = build-test
mkdir /work/source
cp -a /input/. /work/source/
cd /work/source
export HOME=/work/build/home LC_ALL=C.UTF-8 TZ=UTC
export QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/work/runtime QT_FORCE_STDERR_LOGGING=1
mkdir -p "$HOME"
mkdir -m 700 "$XDG_RUNTIME_DIR"
python3 --version
git --version
cmake --version
ninja --version
c++ --version
pkg-config --modversion Qt6Core Qt6Gui Qt6Svg
python3 scripts/ci/test_launcher.py
python3 scripts/ci/prepare-tools.py
export LD_LIBRARY_PATH=/work/tools/usr/lib
export PKG_CONFIG_PATH=/work/tools/usr/lib/pkgconfig
export PKG_CONFIG_SYSROOT_DIR=/work/tools
export QT_PLUGIN_PATH=/work/tools/usr/lib/qt6/plugins
pkg-config --modversion libexif libwebp
cmake -S . -B build/verification -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DBUILD_TESTING=ON
cmake --build build/verification --parallel 2
ctest --test-dir build/verification --output-on-failure --no-tests=error
