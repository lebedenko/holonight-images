#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit host-native preparation; never used during runtime launch.

The output must be a new directory. Build the helper against host libraries first.
Only the four qualified external Qt image plugins and their ELF closure are copied.
PNG/BMP live in QtGui. No SVG plugin or host search directories enter the sandbox.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def prepare(helper, plugins, output):
    helper = helper.resolve(strict=True)
    plugins = plugins.resolve(strict=True)
    output = output.absolute()
    sources = [helper] + [plugins / 'imageformats' / name for name in
                         ('libqgif.so', 'libqjpeg.so', 'libqtiff.so', 'libqwebp.so')]
    env = {'PATH': '/usr/bin', 'LANG': 'C', 'LC_ALL': 'C'}
    files = {helper: 'usr/libexec/holonight-images-helper'}
    for path in sources[1:]:
        files[path] = 'usr/lib/qt6/plugins/imageformats/' + path.name
    for path in sources:
        result = subprocess.run(['/usr/bin/ldd', str(path)], env=env, capture_output=True,
                                text=True, check=True)
        if 'not found' in result.stdout:
            raise ValueError('unresolved dependency: ' + result.stdout)
        for line in result.stdout.splitlines():
            for word in line.split():
                if word.startswith('/'):
                    dependency = Path(word)
                    destination = os.path.normpath(str(dependency))
                    for prefix in ('/lib64/', '/lib/'):
                        if destination.startswith(prefix):
                            destination = '/usr/lib/' + destination[len(prefix):]
                    if not destination.startswith('/usr/'):
                        raise ValueError('unsupported library destination: ' + destination)
                    files[dependency] = destination.lstrip('/')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.isolated-runtime-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'bundle'
        stage.mkdir()
        records = {}
        for source, destination in files.items():
            source = source.resolve(strict=True)
            data = source.read_bytes()
            mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
            record = dict(path=destination, mode=mode, size=len(data), sha256=hashlib.sha256(data).hexdigest())
            if destination in records and records[destination] != record:
                raise ValueError('runtime collision: ' + destination)
            records[destination] = record
            target = stage / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(mode)
            if hashlib.sha256(target.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('runtime copy verification failed')
        manifest = dict(version=1, files=sorted(records.values(), key=lambda r: r['path']))
        data = (json.dumps(manifest, indent=2) + '\n').encode()
        if len(data) > 65536:
            raise ValueError('manifest exceeds runtime bound')
        (stage / 'manifest.json').write_bytes(data)
        (stage / 'manifest.json').chmod(0o644)
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(output), 1):
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(output))
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--plugins', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.helper, args.plugins, args.output)
