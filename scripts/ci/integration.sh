#!/usr/bin/env bash
set -euo pipefail
mkdir -p /work/output
    task build:release
    DESTDIR=/work/package cmake --install build/release
    cmake --install build/release --prefix '/work/external prefix'
    cmake -S tests/package-consumer -B '/work/consumer build' -G Ninja \
      '-DCMAKE_PREFIX_PATH=/work/external prefix'
    cmake --build '/work/consumer build' --parallel "${JOBS:-2}"
    '/work/consumer build/consumer'
    cp -a /work/package /work/output/
