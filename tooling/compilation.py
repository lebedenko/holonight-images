#!/usr/bin/env python3
"""Merge existing native databases; no configuration or build is performed."""
import argparse
import json
import os
import shlex
from pathlib import Path
import subprocess
import tempfile


def discover(root, name):
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in {'.git', '.cache', '.serena'}
                         and d != 'tooling' and 'container' not in d.lower())
        if name in files:
            path = Path(directory) / name
            if path.parent != root and '.cache' not in path.parts:
                yield path


def rank(root, database, source):
    relative = database.relative_to(root)
    parts = relative.parts
    modules = [p for p in root.iterdir() if (p / 'CMakeLists.txt').is_file() or (p / '.git').exists()]
    owner = next((p for p in modules if source.is_relative_to(p)), root)
    dependency = any(p in {'deps', 'dependencies', 'build-dependencies', '_deps'} for p in parts)
    tier = 0 if database.is_relative_to(owner) and not dependency else 1
    names = '/'.join(parts).lower()
    variant = 0 if 'test' in names else 1 if 'debug' in names else 3 if 'release' in names else 2
    canonical = any(parts[i] == 'build' and parts[i + 1] in {'test', 'debug', 'release'} for i in range(len(parts) - 1))
    return tier, variant, 0 if canonical else 1, str(relative)


def merge(root):
    selected, origins, warnings = {}, {}, []
    counts = {'databases': 0, 'stale': 0, 'invalid_entries': 0}
    for database in sorted(discover(root, 'compile_commands.json')):
        try:
            entries = json.loads(database.read_text())
            if not isinstance(entries, list):
                raise ValueError('expected a JSON array')
        except (OSError, ValueError) as exc:
            warnings.append(f'{database.relative_to(root)}: {exc}')
            continue
        counts['databases'] += 1
        for entry in entries:
            if (not isinstance(entry, dict) or not isinstance(entry.get('file'), str)
                    or not isinstance(entry.get('directory'), str)
                    or not entry['file'] or not entry['directory']
                    or not (isinstance(entry.get('command'), str) and entry['command']
                            or isinstance(entry.get('arguments'), list) and entry['arguments']
                            and all(isinstance(x, str) for x in entry['arguments']))):
                counts['invalid_entries'] += 1
                continue
            try:
                arguments = entry.get('arguments') if 'arguments' in entry else shlex.split(entry['command'])
                if not isinstance(arguments, list) or not arguments or not all(isinstance(a, str) for a in arguments) or not arguments[0]:
                    raise ValueError('invalid compiler arguments')
                if Path(arguments[0]).is_absolute() and not Path(arguments[0]).is_file():
                    counts['stale'] += 1
                    continue
            except (ValueError, KeyError):
                counts['invalid_entries'] += 1
                continue
            directory = Path(entry['directory'])
            if not directory.is_absolute():
                directory = database.parent / directory
            directory = directory.resolve()
            source = (directory / entry['file']).resolve()
            if not directory.is_dir() or not source.is_file() or any('container' in p.lower() for p in source.parts + directory.parts):
                counts['stale'] += 1
                continue
            cache = database.parent / 'CMakeCache.txt'
            if cache.is_file():
                import re
                home = re.search(r'^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$', cache.read_text(), re.M)
                if home and not Path(home[1]).is_dir():
                    counts['stale'] += 1
                    continue
            normalized = dict(entry, directory=str(directory), file=str(source))
            priority = rank(root, database, source)
            # JSON tie-break makes output independent of entry order.
            key = priority + (json.dumps(normalized, sort_keys=True),)
            if source not in selected or key < selected[source][0]:
                selected[source] = key, normalized
                origins[str(source)] = str(database.relative_to(root))
    entries = [selected[p][1] for p in sorted(selected)]
    coverage = {}
    for path in selected:
        if path.is_relative_to(root):
            owner = path.relative_to(root).parts[0]
            coverage[owner] = coverage.get(owner, 0) + 1
    tracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--recurse-submodules', '-z'],
                             capture_output=True, text=True)
    sources = {root / p for p in tracked.stdout.split('\0') if p and Path(p).suffix in {'.c', '.cpp', '.cc', '.cxx'}
               and 'tooling' not in Path(p).parts}
    uncovered = [str(p.relative_to(root)) for p in sorted(sources - set(selected)) if p.is_file()]
    return entries, dict(counts, uncovered=uncovered, commands=len(entries), coverage=dict(sorted(coverage.items())),
                         warnings=warnings, origins=dict(sorted(origins.items())))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    entries, report = merge(root)
    if not entries:
        raise SystemExit('No valid compile commands; previous output preserved')
    target = root / 'compile_commands.json'
    atomic_json(target, entries)
    atomic_json(root / '.cache/tooling/coverage.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'origins'}, indent=2))


if __name__ == '__main__':
    main()
