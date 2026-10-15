#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the ordered provider list with ordinary CMake into a disposable prefix."""
import json
import os
from pathlib import Path
import subprocess

root = Path.cwd()
prefix = root / 'build/deps/prefix'
for provider in json.loads((root / 'scripts/ci/providers.json').read_text()):
    name = provider['name']
    source = Path('/work/providers') / name / provider.get('subdirectory', '')
    if provider.get('source_only'):
        continue
    build = root / 'build/deps' / name
    commands = [
        ['cmake', '-S', source, '-B', build, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
         f'-DCMAKE_INSTALL_PREFIX={prefix}', '-DCMAKE_INSTALL_LIBDIR=lib',
         f'-DCMAKE_PREFIX_PATH={prefix}', f'-DQML_IMPORT_PATH={prefix}/lib/qt6/qml',
         # Compatibility with older pinned providers; consumers use normal package discovery.
         f'-DHOLONIGHT_DEPENDENCY_PREFIX={prefix}',
         '-DBUILD_TESTING=OFF', '-DBUILD_TESTS=OFF', '-DBUILD_DEMO=OFF',
         '-DBUILD_CONTROLS_GALLERY=OFF', '-DBUILD_QT5_PROBES=OFF', *provider.get('options', [])],
        ['cmake', '--build', build, '--parallel', os.environ.get('JOBS', '2')],
        ['cmake', '--install', build],
    ]
    for command in commands:
        subprocess.run(list(map(str, command)), check=True)
