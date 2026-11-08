#!/usr/bin/env bash
set -euo pipefail
mkdir -p /work/output
    cmake --preset release -DHOLONIGHT_IMAGES_ISOLATED=ON
    task build:release
    python3 scripts/prepare-isolated-runtime.py --helper build/release/holonight-images-helper \
      --plugins /usr/lib/qt6/plugins --output build/release/acceptance-runtime
    cmake --preset release -DHOLONIGHT_IMAGES_RUNTIME_BUNDLE="$PWD/build/release/acceptance-runtime"
    DESTDIR=/work/package cmake --install build/release
    cmake --install build/release --prefix '/work/external prefix'
    cmake -S tests/package-consumer -B '/work/consumer build' -G Ninja \
      '-DCMAKE_PREFIX_PATH=/work/external prefix'
    cmake --build '/work/consumer build' --parallel "${JOBS:-$(nproc)}"
    '/work/consumer build/consumer'
    cp -a /work/package /work/output/

    cmake -S tests/isolated-consumer -B '/work/isolated consumer build' -G Ninja \
      '-DCMAKE_PREFIX_PATH=/work/external prefix'
    cmake --build '/work/isolated consumer build' --parallel "${JOBS:-$(nproc)}"
