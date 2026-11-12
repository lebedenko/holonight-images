#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Test protected-runtime validation in a disposable root-owned /run fixture.

Run as root with --helper pointing to the native build. No host installation is
modified. The fixture contains inert inventory files, never executed code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile


def exercise(helper):
    if os.geteuid() != 0:
        raise ValueError('requires root for a real protected ancestor chain and UID tests')
    nobody = pwd.getpwnam('nobody')
    helper = helper.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix='holonight-runtime-validation-', dir='/run') as temporary:
        parent = Path(temporary)
        parent.chmod(0o755)
        runtime = parent / 'generation'
        runtime.mkdir(mode=0o755)
        files = []
        for name in ('usr/libexec/holonight-images-helper',
                     'usr/lib/qt6/plugins/imageformats/libqgif.so',
                     'usr/lib/qt6/plugins/imageformats/libqjpeg.so',
                     'usr/lib/qt6/plugins/imageformats/libqtiff.so',
                     'usr/lib/qt6/plugins/imageformats/libqwebp.so'):
            target = runtime / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'fixture')
            target.chmod(0o644)
            files.append(dict(path=name, mode=0o644, size=7,
                              sha256=hashlib.sha256(b'fixture').hexdigest()))
        manifest = runtime / 'manifest.json'
        manifest.write_text(json.dumps(dict(version=1, files=files)))
        manifest.chmod(0o644)

        def verify(accepted):
            result = subprocess.run([str(helper), '--verify-protected-runtime', str(runtime)],
                                    check=False, capture_output=True)
            if (result.returncode == 0) != accepted:
                raise AssertionError(f'protection expectation {accepted}: exit {result.returncode}')

        verify(True)
        for target in (parent, runtime, runtime / 'usr', manifest,
                       runtime / files[0]['path']):
            mode = target.stat().st_mode & 0o7777
            target.chmod(mode | 0o020)
            verify(False)
            target.chmod(mode)
            os.chown(target, nobody.pw_uid, nobody.pw_gid)
            verify(False)
            os.chown(target, 0, 0)
            verify(True)

        alias = parent / 'alias'
        alias.symlink_to(runtime, target_is_directory=True)
        result = subprocess.run([str(helper), '--verify-protected-runtime', str(alias)], check=False)
        if result.returncode == 0:
            raise AssertionError('symlink selection accepted')
        alias.unlink()

        # Real ordinary-user attempts against protected files and directories.
        attempt = (
            'import os, pathlib, sys\n'
            'root = pathlib.Path(sys.argv[1])\n'
            'actions = [lambda: (root / "manifest.json").write_bytes(b"changed"),\n'
            '           lambda: os.chmod(root / "manifest.json", 0o666),\n'
            '           lambda: (root / "injected").write_bytes(b"x")]\n'
            'for action in actions:\n'
            '    try: action()\n'
            '    except PermissionError: continue\n'
            '    raise SystemExit("ordinary-user modification succeeded")\n'
        )
        subprocess.run(['/usr/bin/python3', '-c', attempt, str(runtime)], check=True,
                       user=nobody.pw_uid, group=nobody.pw_gid, extra_groups=[])
        verify(True)
    print('protected runtime: ownership, modes, ancestors, symlinks and ordinary-user writes passed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', required=True, type=Path)
    args = parser.parse_args()
    exercise(args.helper)
