#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded warm-cache validation experiment; never execute runtime payloads."""
import argparse
import difflib
import importlib.util
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import signal
import statistics
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('correctness', HERE.parent / 'hash-correctness/run.py')
correctness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(correctness)
save, digest, inventory, mutate = correctness.save, correctness.digest, correctness.inventory, correctness.mutate
helpers = correctness.helpers
VARIANTS = ('baseline', 'candidate')
POLICY = dict(blocks=3, warmup_pairs=5, measured_pairs=50, child_seconds=60,
              minimum_absolute_ns=4_000_000, minimum_relative=.10, maximum_p95_ratio=1.05,
              cache='warm', retries=0, trimming=False)
PINS = {'summary.json': 'c508c9e65db28799e40ddff6a0b2e23a18b840defc17398911797fdd2ed3742c',
        'observations.json': '5a8de03ccc1167bd11dae80a69d935e5340a60424e376855ac7840e1875733d6',
        'validation.json': '243a4406b17263426d6918d61849090855a0515637540ee812cba75711bbcced',
        'source.tar': 'c0df34691c9c4fec55c7b6bc9a09df5c4efe73dd574a1f47e607a84938d025a0',
        'tooling/candidate.h': '3c3694c6c0041ab5cf0e6ec803f80d718344cca4824586be210c73b78e0c3598',
        'candidate/overlay.patch': '4942b8a30680a73c8c0aac0dbc47d9b29338537916d40aeafa97e817466a2938'}


def schedule():
    for block in range(3):
        for pair in range(55):
            for variant in VARIANTS[::1 if (block + pair) % 2 == 0 else -1]:
                yield dict(block=block, pair=pair, variant=variant,
                           stage='warmup' if pair < 5 else 'measured')


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse(line, expected):
    row = json.loads(line, object_pairs_hook=unique)
    if not isinstance(row, dict) or set(row) != {'accepted', 'total_ns', 'fd_before', 'fd_after'}:
        raise ValueError('incomplete/unexpected output')
    if type(row['accepted']) is not bool or row['accepted'] != expected:
        raise ValueError('verdict mismatch')
    if any(type(row[k]) is not int or row[k] < 0 for k in ('total_ns', 'fd_before', 'fd_after')):
        raise ValueError('invalid numeric output')
    if not 0 < row['total_ns'] <= 60_000_000_000 or row['fd_before'] != row['fd_after']:
        raise ValueError('invalid duration or descriptor leak')
    return row


def summarize(rows):
    expected = list(schedule())
    if len(rows) != len(expected) or any(any(row[k] != item[k] for k in item)
                                        for row, item in zip(rows, expected)):
        raise ValueError('missing, duplicate or misordered samples')
    for row in rows:
        parse(json.dumps({k: row[k] for k in ('accepted', 'total_ns', 'fd_before', 'fd_after')}), True)
    reports = {}
    for block in [0, 1, 2, 'pooled']:
        measured = [r for r in rows if r['stage'] == 'measured' and
                    (block == 'pooled' or r['block'] == block)]
        pairs = {}
        for row in measured:
            pairs.setdefault((row['block'], row['pair']), {})[row['variant']] = row['total_ns']
        absolute = [p['baseline'] - p['candidate'] for p in pairs.values()]
        relative = [(p['baseline'] - p['candidate']) / p['baseline'] for p in pairs.values()]
        distributions = {v: helpers.distribution([r['total_ns'] for r in measured if r['variant'] == v])
                         for v in VARIANTS}
        a, r = statistics.median(absolute), statistics.median(relative)
        # Integer products keep the inclusive 5% boundary exact.
        passes = a >= 4_000_000 and r >= .10 and distributions['candidate']['p95'] * 100 <= distributions['baseline']['p95'] * 105
        reports[str(block)] = dict(variants=distributions, paired_absolute_ns=a,
                                  paired_relative=r, passes=passes, pairs=len(pairs))
    return dict(results=reports, decision=('worthwhile savings demonstrated under tested conditions'
                if all(r['passes'] for r in reports.values()) else 'worthwhile savings not demonstrated'))


class Harness:
    """One lifetime deadline, including idle time; raw bytes survive every failure."""
    def __init__(self, command, prefix, seconds=60):
        self.raw = prefix.with_suffix('.stdout').open('wb')
        self.errors = prefix.with_suffix('.stderr').open('wb')
        self.process = subprocess.Popen(list(map(str, command)), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=self.errors, start_new_session=True)
        self.deadline = time.monotonic() + seconds
        self.expired = threading.Event()
        self.timer = threading.Timer(seconds, self.expire)
        self.timer.daemon = True
        self.timer.start()
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''
        self.fd = None
        self.command = list(map(str, command))

    def expire(self):
        self.expired.set()
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Enforce the lifetime even while the parent is inspecting fixture metadata.
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait(timeout=2)

    def request(self, path):
        if self.expired.is_set() or time.monotonic() >= self.deadline:
            raise TimeoutError('harness lifetime exceeded')
        if self.buffer or self.selector.select(0):
            raise ValueError('unsolicited/duplicate output')
        self.process.stdin.write(os.fsencode(path) + b'\n')
        self.process.stdin.flush()
        while b'\n' not in self.buffer:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise TimeoutError('harness lifetime exceeded')
            part = os.read(self.process.stdout.fileno(), 65536)
            self.raw.write(part)
            self.raw.flush()
            if not part:
                if self.expired.is_set():
                    raise TimeoutError('harness lifetime exceeded')
                raise ValueError('missing/truncated output')
            self.buffer += part
            if len(self.buffer) > 4096:
                raise ValueError('oversized output')
        line, self.buffer = self.buffer.split(b'\n', 1)
        return line

    def close(self, failed=False):
        try:
            self.process.stdin.close()
        except BrokenPipeError:
            pass
        if failed:
            self.expire()
        try:
            remaining = max(0, self.deadline - time.monotonic())
            # stdin is already closed; drain stdout directly after bounded wait.
            self.process.wait(timeout=min(2, remaining))
        except subprocess.TimeoutExpired:
            self.expire()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=2)
        self.timer.cancel()
        self.timer.join()
        rest = self.process.stdout.read()
        self.raw.write(rest)
        self.raw.close()
        self.errors.close()
        self.selector.close()
        self.process.stdout.close()
        return dict(command=self.command, pid=self.process.pid, returncode=self.process.returncode,
                    timeout=self.expired.is_set(), reaped=True,
                    proc_absent=not Path(f'/proc/{self.process.pid}').exists(),
                    trailing=bool(self.buffer or rest))


def qualify(repo, prior, out):
    for name, sha in PINS.items():
        if digest(prior / name) != sha:
            raise ValueError('changed correctness evidence: ' + name)
    provenance = json.loads((prior / 'provenance.json').read_text())
    for name in ('candidate.h', 'run.py', 'device.cpp'):
        if digest(HERE.parent / 'hash-correctness' / name) != provenance['tooling'][name]:
            raise ValueError('changed correctness tooling: ' + name)
    if digest(HERE.parent / 'runtime-profile/profile.py') != provenance['helper_sha256']:
        raise ValueError('changed fixture helpers')
    # Compare all private validation translation units and their project headers.
    paths = [p for directory in ('src/isolated', 'include') for p in (repo / directory).rglob('*')
             if p.suffix in ('.h', '.cpp')]
    hashes = {}
    with tarfile.open(prior / 'source.tar') as archive:
        for path in paths:
            relative = str(path.relative_to(repo))
            if path.read_bytes() != archive.extractfile(relative).read():
                raise ValueError('changed validation source: ' + relative)
            hashes[relative] = digest(path)
    save(out / 'qualified-sources.json', hashes)
    return hashes


def run(fixture, preserved, prior):
    repo = HERE.parents[1]
    out = Path(tempfile.mkdtemp(prefix='hash-performance-', dir=repo / 'build')).resolve()
    print(out, flush=True)
    save(out / 'policy.json', POLICY)
    records, children, rows, validations, failures = [], [], [], [], []
    frozen = None
    report = {}
    def execute(args, cwd=None):
        return correctness.child(args, out, records, cwd=cwd)
    def observe(harness, path, expected, context):
        before = helpers.tree(path)
        line = harness.request(path)
        row = parse(line, expected)
        if helpers.tree(path) != before:
            raise ValueError('fixture metadata changed')
        if harness.fd is not None and row['fd_before'] != harness.fd:
            raise ValueError('descriptor drift between requests')
        harness.fd = row['fd_after']
        return dict(**context, expected=expected, **row)
    def close(harness, context, failed):
        child = dict(**context, **harness.close(failed))
        children.append(child)
        save(out / 'children.json', children)
        if child['returncode'] or child['timeout'] or child['trailing'] or not child['proc_absent']:
            failures.append('harness failure: ' + str(context))
    try:
        frozen = inventory(fixture)
        save(out / 'frozen-before.json', frozen)
        if digest(preserved) != '9d6a0ef8084555b4a31fa6972471b231e44bba4b283c584bb6203d1b00a34127':
            raise ValueError('changed preserved B2 inventory')
        prefix = 'prefix/libexec/holonight-images/runtime/'
        expected = {k[len(prefix):]: v for k, v in json.loads(preserved.read_text()).items() if k.startswith(prefix)}
        if frozen != expected or len(frozen) != 61:
            raise ValueError('frozen fixture mismatch')
        qualified = qualify(repo, prior, out)
        qt = Path('/usr/lib/libQt6Core.so.6').resolve()
        identity = dict(path=str(qt), sha256=digest(qt), package=execute(['pacman', '-Q', 'qt6-base']),
                        notes=execute(['readelf', '-n', qt]))
        save(out / 'qt-identity.json', identity)
        if identity['sha256'] != correctness.QT_HASH or correctness.QT_BUILD_ID not in identity['notes'] or identity['package'].strip() != 'qt6-base 6.12.0-3':
            raise ValueError('QtCore identity changed')
        tooling = out / 'tooling'
        shutil.copytree(HERE, tooling / 'hash-performance', ignore=shutil.ignore_patterns('__pycache__'))
        for directory in ('hash-correctness', 'runtime-profile'):
            shutil.copytree(HERE.parent / directory, tooling / directory, ignore=shutil.ignore_patterns('__pycache__'))
        provenance = dict(host=platform.uname()._asdict(), cpu=Path('/proc/cpuinfo').read_text(),
            load_before=Path('/proc/loadavg').read_text(), compiler=execute(['c++', '--version']),
            dependencies=execute(['pkg-config', '--modversion', 'Qt6Core', 'Qt6Gui']),
            images_head=execute(['git', 'rev-parse', 'HEAD'], repo).strip(),
            tooling=inventory(tooling), reused_evidence=str(prior), reused_hashes=PINS, variants={})
        archive = out / 'source.tar'
        execute(['git', 'archive', '--format=tar', '-o', archive, 'HEAD'], repo)
        provenance['archive_sha256'] = digest(archive)
        for variant in VARIANTS:
            source = out / variant / 'source'
            source.mkdir(parents=True)
            with tarfile.open(archive) as bundle:
                bundle.extractall(source, filter='data')
            for name, sha in qualified.items():
                if digest(source / name) != sha:
                    raise ValueError('HEAD differs from qualified sources')
            shutil.copytree(tooling, source / 'experiments', dirs_exist_ok=True)
            runtime = source / 'src/isolated/runtime.cpp'
            original = runtime.read_text()
            if variant == 'candidate':
                runtime.write_text(correctness.overlay(original))
            patch = out / variant / 'overlay.patch'
            patch.write_text(''.join(difflib.unified_diff(original.splitlines(True), runtime.read_text().splitlines(True),
                fromfile='a/src/isolated/runtime.cpp', tofile='b/src/isolated/runtime.cpp')))
            if variant == 'candidate' and digest(patch) != PINS['candidate/overlay.patch']:
                raise ValueError('candidate overlay changed')
            build = out / variant / 'build'
            execute(['cmake', '-S', source / 'experiments/hash-performance', '-B', build, '-G', 'Ninja',
                     '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'])
            execute(['cmake', '--build', build, '--parallel', '2'])
            binary = build / 'hash-performance'
            provenance['variants'][variant] = dict(binary_sha256=digest(binary), overlay_sha256=digest(patch),
                runtime_sha256=digest(runtime), linked_dependencies=execute(['ldd', binary]),
                compile_commands=json.loads((build / 'compile_commands.json').read_text()))
            save(out / 'provenance.json', provenance)
        for case in correctness.CASES:
            for variant in VARIANTS:
                copy = out / 'fixtures' / case / variant
                shutil.copytree(fixture, copy)
                if inventory(copy) != frozen:
                    raise ValueError('copy mismatch')
                mutate(copy, case)
                before = inventory(copy)
                save(copy.parent / (variant + '-before.json'), before)
                h = Harness([out / variant / 'build/hash-performance'], out / f'case-{case}-{variant}')
                ok = False
                try:
                    validations.append(observe(h, copy, case == 'valid', dict(case=case, variant=variant)))
                    save(out / 'validation.json', validations)
                    ok = True
                finally:
                    close(h, dict(case=case, variant=variant), not ok)
                    after = inventory(copy)
                    save(copy.parent / (variant + '-after.json'), after)
                    if after != before:
                        failures.append('case fixture changed')
                if failures:
                    raise ValueError('validator preflight failed')
        for block in range(3):
            copy = out / 'fixtures' / f'block-{block}'
            shutil.copytree(fixture, copy)
            before = inventory(copy)
            save(out / f'block-{block}-before.json', before)
            if before != frozen:
                raise ValueError('block copy mismatch')
            harnesses, ok = {}, False
            try:
                for variant in VARIANTS:
                    harnesses[variant] = Harness([out / variant / 'build/hash-performance'], out / f'block-{block}-{variant}')
                for context in schedule():
                    if context['block'] == block:
                        rows.append(observe(harnesses[context['variant']], copy, True, context))
                        save(out / 'observations.json', rows)
                ok = True
            finally:
                for variant, h in harnesses.items():
                    close(h, dict(block=block, variant=variant), not ok)
                after = inventory(copy)
                save(out / f'block-{block}-after.json', after)
                if after != before:
                    failures.append('block fixture changed')
            if failures:
                raise ValueError('block failed')
        report = summarize(rows)
        provenance['load_after'] = Path('/proc/loadavg').read_text()
        save(out / 'provenance.json', provenance)
    except Exception as exc:
        failures.append(f'{type(exc).__name__}: {exc}')
    finally:
        if frozen is not None:
            try:
                after = inventory(fixture)
                save(out / 'frozen-after.json', after)
                if after != frozen:
                    failures.append('frozen fixture changed')
            except Exception as exc:
                failures.append('frozen integrity: ' + str(exc))
        if failures:
            report['decision'] = 'no qualified performance result'
        report.update(failures=failures, observations=len(rows), validator_observations=len(validations))
        save(out / 'summary.json', report)
        print(json.dumps(report, indent=2), flush=True)
    return int(bool(failures))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--preserved-inventory', type=Path, required=True)
    parser.add_argument('--correctness-evidence', type=Path, required=True)
    args = parser.parse_args()
    sys.exit(run(args.fixture.resolve(), args.preserved_inventory.resolve(), args.correctness_evidence.resolve()))
