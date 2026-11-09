#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private finite correctness qualification; no measurements or fixture execution."""
import argparse
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('runtime_profile_helpers', HERE.parent / 'runtime-profile/profile.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
save, digest, inventory, mutate = helpers.save, helpers.digest, helpers.inventory, helpers.mutate
QT_HASH = '10635d6f11ff08ed0d81ce3dd6b461b54e90ce29b23aa45d85ad4d50074e022e'
QT_BUILD_ID = '431db715687f9ab0ce66ba4379d344d7b672b510'
CASES = ('valid', 'malformed_manifest', 'duplicate_path', 'missing_required', 'extra_entry',
         'same_size_corruption', 'truncation', 'incorrect_mode', 'special_mode', 'symlink')


def child(args, out, records, seconds=60, cwd=None):
    """Retain raw output even on timeout; terminate the process group and reap."""
    index = len(records)
    record = dict(command=list(map(str, args)), cwd=str(cwd) if cwd else None)
    records.append(record)
    save(out / 'commands.json', records)
    process = subprocess.Popen(record['command'], cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    record['pid'] = process.pid
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=2)
    (out / f'{index:04d}.stdout').write_bytes(stdout)
    (out / f'{index:04d}.stderr').write_bytes(stderr)
    record.update(returncode=process.returncode, timeout=timed_out, reaped=process.poll() is not None,
                  proc_absent=not Path(f'/proc/{process.pid}').exists())
    save(out / 'commands.json', records)
    if timed_out:
        raise TimeoutError('child exceeded deadline')
    if process.returncode or not record['proc_absent']:
        raise ValueError(f'child failed: {record}')
    return stdout.decode()


def parse(text, validator=False):
    try:
        row = json.loads(text)
        if validator:
            if set(row) != {'accepted'} or type(row['accepted']) is not bool:
                raise ValueError('invalid validator output')
        else:
            required = {'completed', 'digest', 'position', 'at_end', 'error', 'file_error', 'reads'}
            if set(row) != required or type(row['completed']) is not bool or type(row['at_end']) is not bool:
                raise ValueError('incomplete device output')
            if (type(row['position']) is not int or type(row['file_error']) is not int or
                    not isinstance(row['error'], str) or not isinstance(row['reads'], list) or
                    not isinstance(row['digest'], str) or len(row['digest']) != 64 or
                    any(c not in '0123456789abcdef' for c in row['digest'])):
                raise ValueError('invalid device output')
            for read in row['reads']:
                if not {'requested', 'returned'} <= read.keys() or any(type(v) is not int for v in read.values()):
                    raise ValueError('invalid read diagnostic')
        return row
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('incomplete output') from exc


def compare(rows, expected=None, completed=None):
    baseline, candidate = rows
    for key in ('completed', 'digest', 'position', 'at_end', 'file_error', 'error'):
        if baseline[key] != candidate[key]:
            raise ValueError(f'{key} mismatch: {baseline[key]!r} != {candidate[key]!r}')
    if expected is not None and baseline['digest'] != expected:
        raise ValueError('expected digest mismatch')
    if completed is not None and baseline['completed'] != completed:
        raise ValueError('expected completion mismatch')


def overlay(text):
    anchor = '!file.open(QIODevice::ReadOnly) || !hash.addData(&file) ||'
    include = '#include "runtime.h"'
    if text.count(anchor) != 1 or text.count(include) != 1 or text.count('hash.addData(&file)') != 1:
        raise ValueError('unexpected runtime source shape')
    return text.replace(include, include + '\n#include "../../experiments/hash-correctness/candidate.h"').replace(
        anchor, '!file.open(QIODevice::ReadOnly) || !HashCorrectness::addData(hash, &file) ||')


def data(size):
    return bytes((i * 37 + i // 251) % 256 for i in range(size))


def sha(content):
    return hashlib.sha256(content).hexdigest()


def scenarios():
    sizes = sorted({0, 1} | {b + d for b in (1024, 16384, 65536, 131072) for d in (-1, 0, 1)})
    for size in sizes:
        yield dict(kind='file', size=size, offset=size, end=True, terminal=0, unbuffered=False)
    for kind in ('closed', 'write-only'):
        yield dict(kind=kind, size=131073, offset=131073, end=True, terminal=0, unbuffered=False)
    for unbuffered in (False, True):
        for offset in (b + d for b in (1024, 16384, 65536) for d in (-1, 0, 1)):
            for terminal in (0, -1):
                for end in (False, True):
                    yield dict(kind='controlled', size=131073, offset=offset, end=end,
                               terminal=terminal, unbuffered=unbuffered)
    for offset in (0, 1023, 1024, 1025, 16383, 16384, 16385, 65535, 65536, 65537):
        yield dict(kind='invalid-fd', size=131073, offset=offset, end=True, terminal=-1, unbuffered=False)


def run(fixture, preserved):
    repo = HERE.parents[1]
    out = Path(tempfile.mkdtemp(prefix='hash-correctness-', dir=repo / 'build')).resolve()
    print(out, flush=True)
    records, observations = [], []
    frozen = None
    summary = dict(decision='stop with no qualified candidate', failures=[], device_cases=0, validation_cases=0)
    def execute(args, cwd=None):
        return child(args, out, records, cwd=cwd)
    try:
        qt = Path('/usr/lib/libQt6Core.so.6').resolve()
        identity = dict(path=str(qt), sha256=digest(qt), notes=execute(['readelf', '-n', qt]),
                        package=execute(['pacman', '-Q', 'qt6-base']))
        save(out / 'qt-identity.json', identity)
        if identity['sha256'] != QT_HASH or QT_BUILD_ID not in identity['notes'] or identity['package'].strip() != 'qt6-base 6.12.0-3':
            raise ValueError('installed QtCore identity changed; provenance must be reconciled again')
        tooling = out / 'tooling'
        shutil.copytree(HERE, tooling, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(HERE.parent / 'runtime-profile/profile.py', out / 'profile-helpers.py')
        provenance = dict(tooling={p.name: digest(p) for p in tooling.iterdir() if p.is_file()},
                          helper_sha256=digest(out / 'profile-helpers.py'),
                          compiler=execute(['c++', '--version']),
                          dependencies=execute(['pkg-config', '--modversion', 'Qt6Core', 'Qt6Gui']))
        save(out / 'provenance.json', provenance)
        native = out / 'device-build'
        execute(['cmake', '-S', tooling, '-B', native, '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release',
                 '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'])
        execute(['cmake', '--build', native, '--parallel', '2'])
        binary = native / 'device-check'
        provenance.update(device_binary_sha256=digest(binary), linked_dependencies=execute(['ldd', binary]))
        save(out / 'provenance.json', provenance)
        for index, case in enumerate(scenarios()):
            content = data(case['size'])
            path = out / 'input.bin'
            path.write_bytes(content)
            result = dict(index=index, scenario=case, full_digest=sha(content),
                          prefix_digest=sha(content[:case['offset']]), variants=[])
            observations.append(result)
            for variant in ('baseline', 'candidate'):
                args = [binary, variant, case['kind'], path, str(case['offset']), str(int(case['end'])),
                        str(case['terminal']), str(int(case['unbuffered']))]
                result['variants'].append(parse(execute(args)))
                save(out / 'observations.json', observations)
            expected, completed = None, None
            if case['kind'] == 'file':
                expected, completed = result['full_digest'], True
            elif case['kind'] in ('closed', 'write-only'):
                expected, completed = sha(b''), False
                if any(r['position'] != 0 or r['reads'] for r in result['variants']):
                    raise ValueError('guard consumed input')
            elif case['kind'] == 'controlled':
                expected, completed = result['prefix_digest'], case['end']
            for row in result['variants']:
                row.update(full_digest_matches=row['digest'] == result['full_digest'],
                           prefix_digest_matches=row['digest'] == result['prefix_digest'])
            save(out / 'observations.json', observations)
            compare(result['variants'], expected, completed)
            summary['device_cases'] += 1
        # Only a device pass authorizes the larger validator experiment.
        prefix = 'prefix/libexec/holonight-images/runtime/'
        prior = json.loads(preserved.read_text())
        frozen = inventory(fixture)
        save(out / 'frozen-before.json', frozen)
        expected = {k[len(prefix):]: v for k, v in prior.items() if k.startswith(prefix)}
        if frozen != expected or len(frozen) != 61:
            raise ValueError('preserved B2 inventory mismatch')
        archive = out / 'source.tar'
        execute(['git', 'archive', '--format=tar', '-o', archive, 'HEAD'], repo)
        provenance.update(images_head=execute(['git', 'rev-parse', 'HEAD'], repo).strip(),
                          archive_sha256=digest(archive), preserved_inventory_sha256=digest(preserved), variants={})
        for variant in ('baseline', 'candidate'):
            source = out / variant / 'source'
            source.mkdir(parents=True)
            with tarfile.open(archive) as bundle:
                bundle.extractall(source, filter='data')
            shutil.copytree(tooling, source / 'experiments/hash-correctness', dirs_exist_ok=True)
            runtime = source / 'src/isolated/runtime.cpp'
            original = runtime.read_text()
            if variant == 'candidate':
                runtime.write_text(overlay(original))
            patch = out / variant / 'overlay.patch'
            patch.write_text(''.join(difflib.unified_diff(original.splitlines(True), runtime.read_text().splitlines(True),
                             fromfile='a/src/isolated/runtime.cpp', tofile='b/src/isolated/runtime.cpp')))
            build = out / variant / 'build'
            execute(['cmake', '-S', source / 'experiments/hash-correctness', '-B', build, '-G', 'Ninja',
                     '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_VALIDATOR=ON', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'])
            execute(['cmake', '--build', build, '--target', 'validation-check', '--parallel', '2'])
            executable = build / 'validation-check'
            provenance['variants'][variant] = dict(binary_sha256=digest(executable), overlay_sha256=digest(patch),
                source_sha256=digest(runtime), linked_dependencies=execute(['ldd', executable]))
            save(out / 'provenance.json', provenance)
        validation = []
        for case in CASES:
            verdicts = []
            for variant in ('baseline', 'candidate'):
                # Retain disposable cases as reproducers, never execute their payloads.
                copy = out / 'fixtures' / case / variant
                shutil.copytree(fixture, copy)
                if inventory(copy) != frozen:
                    raise ValueError('copy inventory mismatch')
                mutate(copy, case)
                before = inventory(copy)
                save(copy.parent / f'{variant}-before.json', before)
                row = parse(execute([out / variant / 'build/validation-check', copy]), validator=True)
                after = inventory(copy)
                save(copy.parent / f'{variant}-after.json', after)
                validation.append(dict(case=case, variant=variant, expected=case == 'valid', **row))
                save(out / 'validation.json', validation)
                if before != after:
                    raise ValueError('disposable fixture mutated')
                verdicts.append(row['accepted'])
            if verdicts != [case == 'valid'] * 2:
                raise ValueError(f'validator verdict mismatch: {case}')
            summary['validation_cases'] += 1
        summary['decision'] = 'bounded correctness agreement established'
    except Exception as exc:
        summary['failures'].append(f'{type(exc).__name__}: {exc}')
    finally:
        if frozen is not None:
            try:
                after = inventory(fixture)
                save(out / 'frozen-after.json', after)
                if frozen != after:
                    raise ValueError('frozen fixture mutated')
            except Exception as exc:
                summary['failures'].append(str(exc))
        if summary['failures']:
            summary['decision'] = 'stop with no qualified candidate'
        save(out / 'summary.json', summary)
        print(json.dumps(summary, indent=2), flush=True)
    return int(bool(summary['failures']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--preserved-inventory', type=Path, required=True)
    args = parser.parse_args()
    sys.exit(run(args.fixture.resolve(), args.preserved_inventory.resolve()))
