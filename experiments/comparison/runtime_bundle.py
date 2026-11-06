#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private, explicit host-native runtime preparation and strict launch preflight."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile

MANIFEST = 'manifest.json'
VERSION = 1
PLUGINS = tuple('/usr/lib/qt6/plugins/imageformats/' + name for name in
                ('libqgif.so', 'libqjpeg.so', 'libqsvg.so', 'libqtiff.so', 'libqwebp.so'))
EXECUTABLES = ('/usr/bin/bwrap', '/usr/bin/xdg-dbus-proxy',
               '/usr/lib/glycin-loaders/2+/glycin-image-rs', '/usr/lib/glycin-loaders/2+/glycin-svg')
CONFIGURATION = '/configuration/glycin-loaders/2+/conf.d/comparison.conf'
REQUIRED = {*PLUGINS, *EXECUTABLES, CONFIGURATION, '/usr/share/mime/mime.cache'}


def host_environment():
    env = {'PATH': '/usr/bin', 'LANG': 'C', 'LC_ALL': 'C'}
    for key in ('XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def destination(value):
    if not isinstance(value, str) or not value.startswith('/') or '\x00' in value:
        raise ValueError('invalid sandbox destination')
    path = PurePosixPath(value)
    if str(path) != value or '..' in path.parts or value == '/':
        raise ValueError('noncanonical sandbox destination')
    # /lib aliases are normalized by preparation; never collide with sandbox state.
    if not (value.startswith('/usr/') or value.startswith('/configuration/')):
        raise ValueError('unsupported sandbox destination')
    return value


def normalized(path):
    value = os.path.normpath(str(path))
    for prefix in ('/lib64/', '/lib/'):
        if value.startswith(prefix):
            return '/usr/lib/' + value[len(prefix):]
    return destination(value)


def loader_configuration():
    text = ''
    for name, signature in (('png', r'0:\\x89PNG'), ('jpeg', r'0:\\xFF\\xD8\\xFF'),
                            ('gif', '0:GIF8'), ('bmp', '0:BM'), ('webp', '0:RIFF,8:WEBP'),
                            ('tiff', r'0:II\\x2a\\x00;0:MM\\x00\\x2a')):
        text += f'[loader:image/{name}]\nExec=/usr/lib/glycin-loaders/2+/glycin-image-rs\nIdentifiers={signature};\n\n'
    return text + '[loader:image/svg+xml]\nExec=/usr/lib/glycin-loaders/2+/glycin-svg\nIdentifiers=ext:svg;\nExposeBaseDir=true\n\n'


def dependencies(paths):
    found = set()
    for path in paths:
        result = subprocess.run(['/usr/bin/ldd', str(path)], env=host_environment(),
                                capture_output=True, text=True, check=True)
        if 'not found' in result.stdout:
            raise ValueError('unresolved library: ' + result.stdout)
        for line in result.stdout.splitlines():
            for word in line.split():
                if word.startswith('/'):
                    dependency = Path(word)
                    if not dependency.is_file():
                        raise ValueError('missing library: ' + word)
                    found.add(dependency)
    return sorted(found)


def validate(root, binary, glycin=False):
    root = Path(root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError('runtime bundle missing or symlinked: ' + str(root))
    manifest_path = root / MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('runtime manifest missing or symlinked')
    if stat.S_IMODE(manifest_path.stat().st_mode) != 0o644:
        raise ValueError('invalid runtime manifest mode')
    manifest = json.loads(manifest_path.read_text())
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'files', 'entries', 'provenance'}
            or type(manifest['version']) is not int or manifest['version'] != VERSION
            or not isinstance(manifest['files'], list) or not manifest['files']
            or not isinstance(manifest['entries'], dict) or not isinstance(manifest['provenance'], dict)):
        raise ValueError('invalid runtime manifest')
    expected = {MANIFEST}
    targets = set()
    records = {}
    for record in manifest['files']:
        if not isinstance(record, dict) or set(record) != {'path', 'destination', 'size', 'mode', 'sha256'}:
            raise ValueError('invalid runtime file record')
        target = destination(record['destination'])
        name = target.lstrip('/')
        if record['path'] != name or name in expected or target in targets:
            raise ValueError('runtime destination collision')
        if (type(record['size']) is not int or record['size'] < 0 or type(record['mode']) is not int
                or record['mode'] not in (0o644, 0o755)
                or not isinstance(record['sha256'], str) or len(record['sha256']) != 64):
            raise ValueError('invalid runtime attributes')
        expected.add(name)
        targets.add(target)
        records[target] = record
    if not REQUIRED <= targets:
        raise ValueError('incomplete runtime inventory')
    if records[CONFIGURATION]['sha256'] != hashlib.sha256(loader_configuration().encode()).hexdigest():
        raise ValueError('invalid generated loader configuration')
    if any(records[target]['mode'] != 0o755 for target in EXECUTABLES):
        raise ValueError('runtime executable mode missing')
    directories = set()
    for name in expected:
        directories.update(str(p) for p in PurePosixPath(name).parents if str(p) != '.')
    for path in root.rglob('*'):
        name = str(path.relative_to(root))
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode) and name in directories:
            continue
        if not stat.S_ISREG(mode) or name not in expected:
            raise ValueError('unexpected runtime entry: ' + name)
    for target, record in records.items():
        path = root / record['path']
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_size != record['size']
                or stat.S_IMODE(info.st_mode) != record['mode'] or digest(path) != record['sha256']):
            raise ValueError('runtime integrity failure: ' + target)
    entries = manifest['entries']
    for identity, entry in entries.items():
        if (not isinstance(entry, dict) or set(entry) != {'destination', 'role', 'sha256'}
                or entry['role'] not in ('qt', 'glycin') or entry['destination'] not in records
                or entry['sha256'] != records[entry['destination']]['sha256']
                or records[entry['destination']]['mode'] != 0o755
                or not Path(identity).is_absolute()):
            raise ValueError('invalid runtime entry point')
    binary = Path(binary).resolve(strict=True)
    entry = entries.get(str(binary))
    if entry is None or entry['role'] != ('glycin' if glycin else 'qt'):
        raise ValueError('unknown or incompatible runtime entry point: ' + str(binary))
    if digest(binary) != entry['sha256']:
        raise ValueError('runtime entry-point identity changed')
    return manifest, entry


def copy_file(stage, files, source, target):
    target = destination(target)
    source = source.resolve(strict=True)
    if not source.is_file():
        raise ValueError('runtime source is not a file')
    mode = 0o755 if source.stat().st_mode & 0o111 else 0o644
    record = dict(path=target.lstrip('/'), destination=target, size=source.stat().st_size,
                  mode=mode, sha256=digest(source))
    if target in files:
        if files[target] != record:
            raise ValueError('conflicting runtime destination: ' + target)
        return
    if any(target.startswith(p + '/') or p.startswith(target + '/') for p in files):
        raise ValueError('runtime file/directory collision')
    files[target] = record
    copied = stage / record['path']
    copied.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, copied)
    copied.chmod(mode)


def publish(stage, output):
    # Linux renameat2(RENAME_NOREPLACE) publishes atomically without overwriting.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(-100, os.fsencode(stage), -100, os.fsencode(output), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(output))


def prepare(build, output, diagnostics=()):
    build, output = Path(build).resolve(), Path(output).absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('runtime output must be new')
    entries = [(build / name, role) for name, role in
               (('qt-worker', 'qt'), ('glycin-worker', 'glycin'), ('fault-worker', 'qt'))]
    entries += [(Path(path).resolve(), role) for path, role in diagnostics]
    plugins = list(map(Path, PLUGINS))
    executables = list(map(Path, EXECUTABLES))
    sources = [p for p, _ in entries] + plugins + executables
    for path in sources:
        if not path.is_file():
            raise ValueError('missing runtime dependency: ' + str(path))
    closure = dependencies(sources)
    mime = Path('/usr/share/mime')
    if not mime.is_dir() or not (mime / 'mime.cache').is_file():
        raise ValueError('missing MIME data')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.runtime-staging-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'bundle'
        stage.mkdir()
        files = {}

        def add(source, target):
            copy_file(stage, files, source, target)

        entry_records = {}
        for index, (path, role) in enumerate(entries):
            target = f'/usr/libexec/comparison/{index}-{path.name}'
            add(path, target)
            entry_records[str(path.resolve())] = dict(destination=target, role=role, sha256=digest(path))
        for path in plugins + executables + closure:
            add(path, normalized(path))
        for path in sorted(mime.rglob('*')):
            if path.is_file():
                add(path, str(path))
            elif not path.is_dir():
                raise ValueError('unsupported MIME entry')
        config = Path(temporary) / 'comparison.conf'
        config.write_text(loader_configuration())
        config.chmod(0o644)
        add(config, CONFIGURATION)
        provenance = {}
        for tool, args in (('/usr/bin/ldd', ['--version']), ('/usr/bin/bwrap', ['--version']),
                           ('/usr/bin/pacman', ['-Q'])):
            result = subprocess.run([tool, *args], env=host_environment(), capture_output=True,
                                    text=True, check=True)
            provenance[tool] = result.stdout
        manifest = dict(version=VERSION, files=sorted(files.values(), key=lambda r: r['path']),
                        entries=entry_records, provenance=provenance)
        (stage / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n')
        (stage / MANIFEST).chmod(0o644)
        validate(stage, entries[0][0])
        publish(stage, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--diagnostic', nargs=2, action='append', default=[], metavar=('PATH', 'ROLE'))
    args = parser.parse_args()
    for _, role in args.diagnostic:
        if role not in ('qt', 'glycin'):
            parser.error('diagnostic role must be qt or glycin')
    output = args.output or args.build / 'runtime-bundle'
    print(prepare(args.build, output, args.diagnostic))


if __name__ == '__main__':
    main()
