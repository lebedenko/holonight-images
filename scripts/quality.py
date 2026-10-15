#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small source-format and compilation-database checks; no dependency preparation."""
import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True)


def owned(suffixes):
    names = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT)
    return sorted({ROOT / name for name in names.decode().split('\0') if name
                   and Path(name).suffix in suffixes and (ROOT / name).is_file()
                   and not set(Path(name).parts) & {'third_party', 'vendor', 'docs', '.serena', 'tooling', 'build'}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['format', 'format-check', 'tidy', 'qmltypes'])
    parser.add_argument('--build', type=Path, default=ROOT / 'build/dev')
    parser.add_argument('--module', action='append', default=[])
    args = parser.parse_args()
    if args.command.startswith('format'):
        if (ROOT / 'scripts/format-sources.py').exists():
            run('python3', 'scripts/format-sources.py', *(['--check'] if args.command == 'format-check' else []))
        else:
            files = owned({'.cpp', '.cc', '.cxx', '.c', '.h', '.hpp'})
            if files:
                run('clang-format', *(['--dry-run', '--Werror'] if args.command == 'format-check' else ['-i']), *files)
            if (ROOT / 'scripts/qt-tool.py').exists():
                formatter = subprocess.check_output(['python3', str(ROOT / 'scripts/qt-tool.py'),
                                                     '--tool', 'qmlformat'], text=True).strip()
                for path in sorted((ROOT / 'qml').rglob('*.qml')):
                    if args.command == 'format':
                        run(formatter, '-i', path)
                    elif subprocess.check_output([formatter, str(path)]) != path.read_bytes():
                        raise RuntimeError(f'QML formatting differs: {path}')
    elif args.command == 'tidy':
        sources = set(owned({'.cpp', '.cc', '.cxx', '.c'}))
        # Installed-package regressions generate independent consumer databases during CTest.
        databases = sorted(args.build.rglob('compile_commands.json'))
        if not databases:
            raise RuntimeError(f'No compilation database in {args.build}; build with tests first')
        # Restrict header diagnostics to owned source directories, never generated
        # build headers or external /usr/include trees with similar path segments.
        header_paths = [p.relative_to(ROOT) for p in owned({'.h', '.hpp', '.inc'})]
        header_roots = {re.escape(p.parts[0]) + ('/' if len(p.parts) > 1 else '$') for p in header_paths}
        header_filter = '^' + re.escape(str(ROOT)) + '/(' + '|'.join(sorted(header_roots)) + ')'
        covered = set()
        commands = []
        for database in databases:
            files = {Path(e['file']).resolve() for e in json.loads(database.read_text())} & sources
            for path in sorted(files):
                config = ROOT / 'tests/.clang-tidy' if 'tests' in path.relative_to(ROOT).parts else ROOT / '.clang-tidy'
                if not config.exists():
                    config = ROOT / '.clang-tidy'
                commands.append(('clang-tidy', '--quiet', path, '-p', database.parent, f'--config-file={config}', f'--header-filter={header_filter}', '--warnings-as-errors=*'))
            covered |= files
        with ThreadPoolExecutor(max_workers=int(os.environ.get('JOBS', '2'))) as pool:
            list(pool.map(lambda command: run(*command), commands))
        if not covered:
            raise RuntimeError('No owned sources were checked by clang-tidy')
    else:
        artifacts = [p for p in args.build.rglob('qmldir') if 'tests' not in p.relative_to(args.build).parts]
        for uri in args.module:
            matching = [p for p in artifacts if f'module {uri}\n' in p.read_text()]
            if not matching:
                raise RuntimeError(f'Missing QML module {uri}')
            for qmldir in matching:
                for name in re.findall(r'^typeinfo\s+(\S+)', qmldir.read_text(), re.M):
                    path = qmldir.parent / name
                    if not path.is_file() or not re.search(r'\bModule\s*\{', path.read_text()):
                        raise RuntimeError(f'Missing or empty QML type metadata: {path}')


if __name__ == '__main__':
    main()
