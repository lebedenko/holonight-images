#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded private host-native full-validation experiment; never executes fixture files."""
import argparse
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import selectors
import shutil
import statistics
import subprocess
import tarfile
import tempfile
import time

PHASES = {'manifest_load_parse', 'record_metadata', 'file_open', 'read_hash',
          'record_finish', 'required_entries', 'inventory'}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            result[str(path.relative_to(root))] = {'symlink': os.readlink(path)}
        elif path.is_file():
            result[str(path.relative_to(root))] = dict(
                mode=path.stat().st_mode & 0o7777, bytes=path.stat().st_size, sha256=digest(path))
        elif not path.is_dir():
            raise ValueError('unexpected fixture type')
    return result


def tree(root):
    return {str(p.relative_to(root)): (p.lstat().st_mode, p.lstat().st_size,
                                     p.lstat().st_mtime_ns, p.lstat().st_ctime_ns)
            for p in root.rglob('*')}


def overlay(text):
    """Insert observation boundaries only; retain the original conditional expressions."""
    edits = [
        ('#include "runtime.h"', '#include "runtime.h"\n#include "../../experiments/runtime-profile/telemetry.h"'),
        ('QStringList validate(const QString& root) {',
         'QStringList validate(const QString& root) {\n  Profile::Recorder profile;'),
        ('  QSet<QString> expected', '  profile.mark("record_metadata");\n  QSet<QString> expected'),
        ('    const auto path = record["path"].toString();',
         '    const auto path = record["path"].toString();\n    profile.path = path;'),
        ('    QFile file(absolute);',
         '    profile.mark("file_open", path, info.st_size);\n    QFile file(absolute);'),
        ('!file.open(QIODevice::ReadOnly) || !hash.addData(&file) ||',
         '!file.open(QIODevice::ReadOnly) ||\n        (profile.mark("read_hash", path, info.st_size), false) || !hash.addData(&file) ||'),
        ('    binds << "--ro-bind" << absolute << "/" + path;',
         '    profile.mark("record_finish", path, info.st_size);\n'
         '    binds << "--ro-bind" << absolute << "/" + path;\n'
         '    profile.mark("record_metadata");'),
        ('  for (const auto* required :', '  profile.mark("required_entries");\n  for (const auto* required :'),
        ('  QDirIterator entries(root,', '  profile.mark("inventory");\n  QDirIterator entries(root,'),
    ]
    for old, new in edits:
        if text.count(old) != 1:
            raise ValueError('overlay anchor changed: ' + old)
        text = text.replace(old, new)
    return text


def parse_line(line, instrumented, expected, files=None):
    try:
        row = json.loads(line)
        if type(row['accepted']) is not bool or row['accepted'] != expected:
            raise ValueError('unexpected validation result')
        for field in ('total_ns', 'fd_before', 'fd_after'):
            if type(row[field]) is not int or row[field] < 0:
                raise ValueError('invalid numeric telemetry')
        if row['total_ns'] == 0 or row['fd_before'] != row['fd_after']:
            raise ValueError('invalid duration or descriptor leak')
        events = row['events']
        if not isinstance(events, list) or bool(events) != instrumented:
            raise ValueError('missing/unexpected phases')
        for event in events:
            if (event['phase'] not in PHASES or type(event['ns']) is not int or event['ns'] < 0
                    or not isinstance(event['path'], str)
                    or (event['bytes'] is not None and
                        (type(event['bytes']) is not int or event['bytes'] < 0))):
                raise ValueError('invalid phase')
        if sum(e['ns'] for e in events) > row['total_ns']:
            raise ValueError('phase coverage exceeds total')
        if instrumented and expected:
            if {e['phase'] for e in events} != PHASES:
                raise ValueError('incomplete phases')
            if files is not None:
                for phase in ('file_open', 'read_hash', 'record_finish'):
                    actual = [(e['path'], e['bytes']) for e in events if e['phase'] == phase]
                    if sorted(actual) != sorted(files.items()):
                        raise ValueError('missing or duplicate file observation')
        return row
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError('malformed/truncated telemetry') from exc


def distribution(values):
    values = sorted(values)
    return dict(n=len(values), median=statistics.median(values) if values else None,
                p95=values[math.ceil(.95 * len(values)) - 1] if values else None)


def summarize(rows, failures, expected=100):
    result = dict(expected_per_variant=expected, failures=failures, failure_count=len(failures),
                  warmups={v: sum(r['variant'] == v and r['stage'] == 'warmup' for r in rows)
                           for v in ('baseline', 'instrumented')}, variants={})
    for variant in ('baseline', 'instrumented'):
        samples = [r for r in rows if r['variant'] == variant and r['stage'] == 'measured']
        accepted = [r for r in samples if r['accepted']]
        phases = {p: distribution([sum(e['ns'] for e in r['events'] if e['phase'] == p)
                                  for r in accepted if any(e['phase'] == p for e in r['events'])])
                  for p in sorted(PHASES)}
        result['variants'][variant] = dict(observations=len(samples), accepted=len(accepted),
            rejected=len(samples) - len(accepted), missing=max(0, expected - len(samples)),
            total_ns=distribution([r['total_ns'] for r in accepted]), phases_ns=phases,
            phase_coverage=distribution([sum(e['ns'] for e in r['events']) / r['total_ns']
                                        for r in accepted if r['events']]),
            descriptor_counts=sorted({r[k] for r in samples for k in ('fd_before', 'fd_after')}))
    base = result['variants']['baseline']['total_ns']['median']
    inst = result['variants']['instrumented']['total_ns']['median']
    complete = not failures and all(v['accepted'] == expected and v['missing'] == 0
                                   for v in result['variants'].values())
    overhead = inst / base - 1 if base and inst is not None else None
    result.update(complete=complete, median_overhead_fraction=overhead,
                  attribution=('incomplete' if not complete else
                               'materially perturbed' if abs(inst - base) > base * .10 else 'within 10%'))
    paths = sorted({e['path'] for r in rows if r['stage'] == 'measured' and r['accepted']
                    for e in r['events'] if e['phase'] == 'read_hash'})
    result['files'] = {p: {phase: distribution([e['ns'] for r in rows
        if r['stage'] == 'measured' and r['accepted'] for e in r['events']
        if e['path'] == p and e['phase'] == phase])
        for phase in ('file_open', 'read_hash', 'record_finish')} for p in paths}
    for path in paths:
        result['files'][path]['bytes'] = sorted({e['bytes'] for r in rows
            if r['stage'] == 'measured' and r['accepted'] for e in r['events']
            if e['path'] == path and e['phase'] == 'read_hash'})
    return result


class Harness:
    def __init__(self, binary, log, seconds=60):
        self.errors = log.open('wb')
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.errors)
        self.deadline = time.monotonic() + seconds
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''

    def request(self, path):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('60-second harness lifetime exceeded')
        self.process.stdin.write(os.fsencode(path) + b'\n')
        self.process.stdin.flush()
        while b'\n' not in self.buffer:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError('60-second harness lifetime exceeded')
            part = os.read(self.process.stdout.fileno(), 65536)
            if not part:
                raise ValueError('truncated telemetry: ' + repr(self.buffer))
            self.buffer += part
            if len(self.buffer) > 1024 * 1024:
                raise ValueError('oversized telemetry')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line

    def close(self):
        # Always terminate and reap, including timeout/error paths.
        self.process.stdin.close()
        if self.process.poll() is None:
            self.process.terminate()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=2)
        self.process.stdout.close()
        self.selector.close()
        self.errors.close()
        return dict(pid=self.process.pid, returncode=self.process.returncode,
                    reaped=self.process.poll() is not None,
                    proc_absent=not Path(f'/proc/{self.process.pid}').exists(),
                    trailing_telemetry=self.buffer.decode(errors='replace'))


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT)


def build(repo, out):
    archive = out / 'source.tar'
    subprocess.run(['git', 'archive', '--format=tar', '-o', str(archive), 'HEAD'], cwd=repo, check=True)
    provenance = dict(images_revision=command(['git', 'rev-parse', 'HEAD'], repo).strip(),
        umbrella_revision=command(['git', 'rev-parse', 'HEAD'], repo.parent).strip(),
        source_archive_sha256=digest(archive), kernel=platform.uname()._asdict(),
        compiler=command(['c++', '--version']), cmake=command(['cmake', '--version']),
        dependencies=command(['pkg-config', '--modversion', 'Qt6Core', 'Qt6Gui']), variants={})
    for variant in ('baseline', 'instrumented'):
        source = out / variant / 'source'
        source.mkdir(parents=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(source, filter='data')
        shutil.copytree(Path(__file__).parent, source / 'experiments/runtime-profile', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__'))
        runtime = source / 'src/isolated/runtime.cpp'
        original = runtime.read_text()
        if variant == 'instrumented':
            runtime.write_text(overlay(original))
        patch = ''.join(difflib.unified_diff(original.splitlines(True), runtime.read_text().splitlines(True),
                                            fromfile='a/src/isolated/runtime.cpp', tofile='b/src/isolated/runtime.cpp'))
        (out / variant / 'overlay.patch').write_text(patch)
        build_dir = out / variant / 'build'
        commands = [['cmake', '-S', str(source / 'experiments/runtime-profile'), '-B', str(build_dir),
                     '-G', 'Ninja', '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'],
                    ['cmake', '--build', str(build_dir), '--parallel', '2']]
        save(out / variant / 'commands.json', commands)
        with (out / variant / 'build.log').open('w') as log:
            for args in commands:
                subprocess.run(args, stdout=log, stderr=subprocess.STDOUT, check=True)
        binary = build_dir / 'runtime-profile'
        provenance['variants'][variant] = dict(binary_sha256=digest(binary),
            patch_sha256=digest(out / variant / 'overlay.patch'),
            linked_dependencies=command(['ldd', str(binary)]),
            compile_commands=json.loads((build_dir / 'compile_commands.json').read_text()))
        save(out / 'provenance.json', provenance)
    return provenance


def mutate(root, case):
    manifest = root / 'manifest.json'
    data = json.loads(manifest.read_text())
    leaf = root / data['files'][0]['path']
    if case == 'malformed_manifest':
        manifest.write_text('{')
    elif case == 'duplicate_path':
        data['files'].append(data['files'][0])
        save(manifest, data)
    elif case == 'missing_required':
        data['files'] = [r for r in data['files'] if r['path'] != 'usr/libexec/holonight-images-helper']
        save(manifest, data)
    elif case == 'extra_entry':
        (root / 'extra').write_text('extra')
    elif case == 'same_size_corruption':
        with leaf.open('r+b') as stream:
            first = stream.read(1)
            stream.seek(0)
            stream.write(bytes([first[0] ^ 1]))
    elif case == 'truncation':
        with leaf.open('r+b') as stream:
            stream.truncate(1)
    elif case in ('incorrect_mode', 'special_mode'):
        leaf.chmod(0o600 if case == 'incorrect_mode' else 0o4755)
    elif case == 'symlink':
        leaf.unlink()
        leaf.symlink_to(root / data['files'][1]['path'])
    elif case != 'valid':
        raise ValueError(case)


def run(repo, fixture, preserved):
    out = Path(tempfile.mkdtemp(prefix='runtime-profile-', dir=repo / 'build')).resolve()
    print(out, flush=True)
    rows, failures, children = [], [], []
    frozen_before = None
    copied_before = None
    raw = (out / 'observations.jsonl').open('w')
    wire = (out / 'wire.jsonl').open('w')
    def observe(harness, variant, path, stage, case, expected, files):
        before = tree(path)
        line = harness.request(path)
        wire.write(json.dumps(dict(variant=variant, stage=stage, case=case,
                                  line=line.decode(errors='replace'))) + '\n')
        wire.flush()
        row = parse_line(line, variant == 'instrumented', expected, files)
        if tree(path) != before:
            raise ValueError('fixture mutation during validation')
        row.update(variant=variant, stage=stage, case=case)
        rows.append(row)
        raw.write(json.dumps(row) + '\n')
        raw.flush()
    try:
        # Compare every file to the preserved B2 evidence, including manifest modes/hash.
        prefix = 'prefix/libexec/holonight-images/runtime/'
        prior = json.loads(preserved.read_text())
        expected_inventory = {k[len(prefix):]: v for k, v in prior.items() if k.startswith(prefix)}
        frozen_before = inventory(fixture)
        if frozen_before != expected_inventory or len(frozen_before) != 61:
            raise ValueError('frozen fixture differs from preserved 60-file evidence')
        save(out / 'frozen-before.json', frozen_before)
        copy = out / 'runtime'
        shutil.copytree(fixture, copy, copy_function=shutil.copy2)
        copied_before = inventory(copy)
        if copied_before != frozen_before:
            raise ValueError('fixture copy differs')
        save(out / 'copy-before.json', copied_before)
        files = {r['path']: r['size'] for r in json.loads((copy / 'manifest.json').read_text())['files']}
        provenance = build(repo, out)
        provenance.update(fixture=str(fixture), preserved_inventory=str(preserved),
                          preserved_inventory_sha256=digest(preserved),
                          payload_files=len(files), payload_bytes=sum(files.values()))
        save(out / 'provenance.json', provenance)
        for stage in ('correctness', 'measurement'):
            harnesses = {}
            try:
                for variant in ('baseline', 'instrumented'):
                    harnesses[variant] = Harness(out / variant / 'build/runtime-profile',
                                                out / f'{stage}-{variant}.stderr')
                if stage == 'correctness':
                    for case in ('valid', 'malformed_manifest', 'duplicate_path', 'missing_required',
                                 'extra_entry', 'same_size_corruption', 'truncation',
                                 'incorrect_mode', 'special_mode', 'symlink'):
                        # Separate disposable copies prevent one fault from contaminating the next.
                        with tempfile.TemporaryDirectory(prefix='fault-', dir=out) as temporary:
                            fault = Path(temporary) / 'runtime'
                            shutil.copytree(copy, fault)
                            mutate(fault, case)
                            fault_before = inventory(fault)
                            for variant, harness in harnesses.items():
                                observe(harness, variant, fault, stage, case, case == 'valid', files)
                            if inventory(fault) != fault_before:
                                raise ValueError('fault fixture mutated')
                else:
                    for i in range(105):
                        order = ('baseline', 'instrumented') if i % 2 == 0 else ('instrumented', 'baseline')
                        for variant in order:
                            observe(harnesses[variant], variant, copy,
                                    'warmup' if i < 5 else 'measured', i, True, files)
                if inventory(copy) != copied_before:
                    raise ValueError('copied fixture mutated')
            finally:
                for variant, harness in harnesses.items():
                    child = dict(stage=stage, variant=variant, **harness.close())
                    children.append(child)
                    if not child['reaped'] or not child['proc_absent'] or child['trailing_telemetry']:
                        failures.append('harness cleanup/trailing telemetry failure')
            if failures:
                break
    except Exception as exc:
        failures.append(f'{type(exc).__name__}: {exc}')
    finally:
        raw.close()
        wire.close()
        for label, root, before in [('frozen', fixture, frozen_before),
                                    ('copy', out / 'runtime', copied_before)]:
            if before is not None:
                try:
                    after = inventory(root)
                    save(out / f'{label}-after.json', after)
                    if after != before:
                        failures.append(label + ' fixture integrity failure')
                except Exception as exc:
                    failures.append(f'{label} integrity check: {exc}')
        save(out / 'children.json', children)
        report = summarize(rows, failures)
        save(out / 'summary.json', report)
        print(json.dumps(report['variants'], indent=2), flush=True)
        print('Attribution:', report['attribution'], 'Failures:', failures, flush=True)
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--preserved-inventory', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(Path(__file__).resolve().parents[2], args.fixture.resolve(),
                         args.preserved_inventory.resolve()))
