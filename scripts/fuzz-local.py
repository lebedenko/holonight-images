#!/usr/bin/env python3
"""Generate reproducible seeds, replay them and run bounded local sanitizer campaigns."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parent.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory):
    return {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob('*')) if p.is_file()}


def seeds(output):
    spec = importlib.util.spec_from_file_location('fixtures', ROOT / 'tests/format-fixtures.py')
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    containers = {**fixtures.TIFF_FIXTURES, **fixtures.GIF_FIXTURES,
                  **fixtures.FORMATS, 'compact.webp': fixtures.compact_webp,
                  'extended.webp': fixtures.extended_webp, 'animated.webp': fixtures.animated_webp}
    exifs = {}
    for orientation in range(1, 9):
        tiff = fixtures.tiff_header('<') + fixtures.tiff_ifd('<', 8, [(274, 'SHORT', [orientation]),
                                                                         (271, 'ASCII', b'Camera\0')])
        exif = b'Exif\0\0' + tiff
        exifs[f'orientation-{orientation}'] = exif
        containers[f'orientation-{orientation}.jpg'] = (fixtures.jpeg[:2] + b'\xff\xe1' +
            struct.pack('>H', len(exif) + 2) + exif + fixtures.jpeg[2:])
        containers[f'orientation-{orientation}.png'] = (fixtures.png[:33] +
            fixtures.chunk(b'eXIf', tiff) + fixtures.png[33:])
        containers[f'orientation-{orientation}.webp'] = fixtures.riff(
            fixtures.riff_chunk(b'VP8X', b'\x08' + bytes(9)) + fixtures.compact_webp[12:] +
            fixtures.riff_chunk(b'EXIF', exif))
    for harness, inputs in [('exif', exifs), ('metadata', containers), ('decode', containers)]:
        directory = output / 'seeds' / harness
        directory.mkdir(parents=True)
        for name, data in inputs.items():
            variants = {'full': data, 'half': data[:len(data)//2], 'short': data[:7],
                        'bad-offset': data[:4] + b'\xff' * 4 + data[8:]}
            for variant, payload in variants.items():
                (directory / f'{name}-{variant}').write_bytes(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--harness', choices=('all', 'exif', 'metadata', 'decode'), default='all')
    parser.add_argument('--seed', type=int, default=20260923)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('--seconds must be within 1..600')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        parser.error('use an empty output directory; evidence is never overwritten')
    seeds(output)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:allocator_may_return_null=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1', QT_QPA_PLATFORM='offscreen')
    record = {'seed': args.seed, 'seconds': args.seconds, 'environment': {k: env[k] for k in
              ('ASAN_OPTIONS', 'UBSAN_OPTIONS', 'QT_QPA_PLATFORM')},
              'seed_hashes': inventory(output / 'seeds'), 'commands': [], 'results': [],
              'versions': {}, 'runner_sha256': digest(Path(__file__)), 'source_hashes': {str(p.relative_to(ROOT)): digest(p)
                for folder in ('src', 'include', 'fuzz') for p in (ROOT / folder).rglob('*') if p.is_file()}}
    for name, command in {'clang': ['clang++', '--version'], 'qt': ['pkg-config', '--modversion', 'Qt6Core'],
                          'codecs': ['pkg-config', '--modversion', 'libexif', 'libwebp'],
                          'revision': ['git', '-C', str(ROOT), 'rev-parse', 'HEAD']}.items():
        record['versions'][name] = subprocess.check_output(command, text=True).strip()
    cache = args.build.resolve() / 'CMakeCache.txt'
    record['cmake_cache'] = cache.read_text()
    failed = False
    for harness in (('exif', 'metadata', 'decode') if args.harness == 'all' else (args.harness,)):
        binary = args.build.resolve() / 'fuzz' / f'fuzz-{harness}'
        record.setdefault('binaries', {})[harness] = digest(binary)
        corpus = output / 'corpus' / harness
        shutil.copytree(output / 'seeds' / harness, corpus)
        artifacts = output / 'artifacts' / harness
        artifacts.mkdir(parents=True)
        common = [str(binary), '-max_len=1048576', '-rss_limit_mb=2048', '-timeout=10',
                  f'-seed={args.seed}', f'-artifact_prefix={artifacts}/']
        for phase, flags, directory in [('replay', ['-runs=0'], output / 'seeds' / harness),
                                         ('campaign', [f'-max_total_time={args.seconds}'], corpus)]:
            command = common + flags + [str(directory)]
            record['commands'].append(command)
            start = time.monotonic()
            with (output / f'{harness}-{phase}.log').open('w') as log:
                try:
                    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=env,
                                            timeout=args.seconds + 20 if phase == 'campaign' else 120)
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 'wall-timeout'
            record['results'].append({'harness': harness, 'phase': phase, 'returncode': code,
                                      'elapsed_seconds': time.monotonic() - start})
            failed |= code != 0
            record['corpus_hashes'] = inventory(output / 'corpus')
            record['artifact_hashes'] = inventory(output / 'artifacts')
            (output / 'campaign.json').write_text(json.dumps(record, indent=2) + '\n')
            print(f'{harness} {phase}: {code}', flush=True)
            if code != 0:
                break
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
