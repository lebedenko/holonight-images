#!/bin/sh
set -eu
lane=$1
mkdir /work/source
cp -a /input/. /work/source/
cd /work/source
export HOME=/work/build/home LC_ALL=C.UTF-8 TZ=UTC
export QT_QPA_PLATFORM=offscreen XDG_RUNTIME_DIR=/work/runtime QT_FORCE_STDERR_LOGGING=1
export XDG_DATA_HOME=/work/data XDG_CONFIG_HOME=/work/config XDG_CACHE_HOME=/work/cache
mkdir -p "$HOME" "$XDG_DATA_HOME" "$XDG_CONFIG_HOME" "$XDG_CACHE_HOME"
mkdir -m 700 "$XDG_RUNTIME_DIR"
if [ "$lane" = licensing ]; then
  reuse --version
  reuse --no-multiprocessing lint
  exit
fi
if [ "$lane" = prepare ]; then
  task deps PRESET=test
  python3 tooling/external.py check --module tooling/module.json --scope build --scope tool --scope test
  pacman -Q > /prepared/packages.txt
  c++ --version > /prepared/compiler.txt
  cmake --version > /prepared/cmake.txt
  { python3 --version; ninja --version; clang++ --version; clang-tidy --version;
    pkg-config --modversion Qt6Core Qt6Gui Qt6Svg libexif libwebp;
    pacman -Q gtest qt6-imageformats; } > /prepared/versions.txt
  cp build/deps/external-state.json /prepared/external-state.json
  exit
fi
cat /prepared/compiler.txt /prepared/cmake.txt /prepared/versions.txt
cp /prepared/packages.txt /prepared/compiler.txt /prepared/cmake.txt /prepared/versions.txt /output/
case "$lane" in
  build-test)
    python3 scripts/ci/test_launcher.py
    python3 scripts/ci/test_dependencies.py
    # Keep the established Release provider-test configuration.
    cmake -S . -B build/verification -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DBUILD_TESTING=ON
    cmake --build build/verification --parallel "${JOBS:-2}"
    ctest --test-dir build/verification --output-on-failure --no-tests=error
    cat build/verification/Testing/Temporary/LastTest.log
    cp -a build/verification/Testing /output/
    # Optional harnesses retain their existing Clang/libFuzzer interfaces.
    cmake -S . -B build/fuzz -G Ninja -DCMAKE_CXX_COMPILER=clang++ \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF -DHOLONIGHT_IMAGES_FUZZING=ON
    cmake --build build/fuzz --parallel "${JOBS:-2}"
    ;;
  release)
    python3 tooling/workflow.py build --preset release
    DESTDIR=/work/package cmake --install build/release
    cmake --install build/release --prefix '/work/external prefix'
    cmake -S tests/package-consumer -B '/work/consumer build' -G Ninja \
      '-DCMAKE_PREFIX_PATH=/work/external prefix'
    cmake --build '/work/consumer build' --parallel "${JOBS:-2}"
    '/work/consumer build/consumer'
    cp -a /work/package /output/
    ;;
  static-checks)
    git init -q
    git add .
    python3 tooling/workflow.py build --preset test
    ctest --preset test -R installed-package
    cat build/test/Testing/Temporary/LastTest.log
    cmake -S . -B build/fuzz -G Ninja -DCMAKE_CXX_COMPILER=clang++ \
      -DCMAKE_BUILD_TYPE=RelWithDebInfo -DBUILD_TESTING=OFF -DHOLONIGHT_IMAGES_FUZZING=ON \
      -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    cmake --build build/fuzz --parallel "${JOBS:-2}"
    python3 tooling/workflow.py format-check
    python3 tooling/workflow.py tidy --scope all
    ;;
  *) echo "Unknown lane: $lane" >&2; exit 2 ;;
esac
