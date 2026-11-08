#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build and verify the opt-in native runtime without deploying anything."""
import argparse
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, default=ROOT / 'build/isolated')
    parser.add_argument('--build-type', choices=('Debug', 'Release'), default='Debug')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    build = args.build.absolute()
    run('cmake', '-S', ROOT, '-B', build, '-G', 'Ninja', '-DHOLONIGHT_IMAGES_ISOLATED=ON',
        '-DBUILD_TESTING=ON', '-DHOLONIGHT_IMAGES_RUNTIME_TESTING=ON', '-DCMAKE_INSTALL_LIBDIR=lib',
        '-DCMAKE_BUILD_TYPE=' + args.build_type)
    run('cmake', '--build', build, '-j', args.jobs)
    # Keep unique evidence and bundles under the ignored build tree.
    evidence = Path(tempfile.mkdtemp(prefix='runtime-', dir=build))
    for helper, name in ((build / 'holonight-images-helper', 'production'),
                         (build / 'tests/isolated-fault-helper', 'fault')):
        run(sys.executable, ROOT / 'scripts/prepare-isolated-runtime.py', '--helper', helper,
            '--plugins', '/usr/lib/qt6/plugins', '--output', evidence / name)
    run('cmake', '-S', ROOT, '-B', build,
        '-DHOLONIGHT_IMAGES_RUNTIME_BUNDLE=' + str(evidence / 'production'),
        '-DHOLONIGHT_IMAGES_FAULT_RUNTIME=' + str(evidence / 'fault'))
    try:
        run('ctest', '--test-dir', build, '--output-on-failure', '--output-log', evidence / 'ctest.log')
    finally:
        test_log = build / 'Testing/Temporary/LastTest.log'
        if test_log.is_file():
            shutil.copyfile(test_log, evidence / 'tests.log')
    print('Native runtime evidence:', evidence)


if __name__ == '__main__':
    main()
