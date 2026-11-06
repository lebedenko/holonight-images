#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Descriptor acquisition, isolated discovery and immutable capsule evidence."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

from color import encode
from runtime_evidence import guarded_main, Invocation, destination, require
from runtime_suites import scenarios, requirements

from harness import RequestCancelled, Worker, validate_paths
from linked import acquire
from runtime_trace import analyze, require_trial
from runtime_bundle import validate


def sha(data):
    return hashlib.sha256(data).hexdigest()


def svg(paths):
    images = ''.join(f'<image x="{i}" width="1" height="1" href="{path}"/>'
                     for i, path in enumerate(paths))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{len(paths)}" height="1">'
            f'{images}</svg>').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('--focused', action='store_true')
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--runtime-bundle', type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    root = destination(args, build, 'linked-')
    options = dict(focused=args.focused)
    options.update(build=str(build), runtime_bundle=str((args.runtime_bundle or build / 'runtime-bundle').resolve()),
                   evidence_dir=str(root))
    invocation = Invocation(root, 'linked', options, scenarios('linked', options), requirements('linked', options))
    invocation.runtime_bundle = args.runtime_bundle
    report = dict(results=[], scopes=[])
    results = report['results']
    invocation.report['records'] = results

    def check(name, action):
        record = dict(name=name)
        results.append(record)
        invocation.scenario(name)
        try:
            action(record)
            record['status'] = 'passed'
        except Exception as error:
            record.update(status='failed', error=repr(error))
        invocation.checkpoint()

    def inputs(name, document, resource=None):
        source = root / name / 'originals'
        source.mkdir(parents=True)
        (source / 'child').mkdir()
        (source.parent / 'input.svg').write_bytes(document)
        (source / 'source.svg').write_bytes(document)
        if resource is not None:
            (source / 'pixel.png').write_bytes(resource)
            (source / 'child/pixel.png').write_bytes(resource)
        (source / 'unreadable').write_bytes(b'unreferenced')
        (source / 'unreadable').chmod(0)
        # A FIFO would block an accidental recursive file acquisition.
        os.mkfifo(source / 'unreferenced-fifo')
        return source

    def trace_evidence(source, trace, backend='qt'):
        findings = analyze(trace.read_text(), cwd=str(Path.cwd()), protected=[source, source.parent / 'pinned'])
        selected = invocation.runtime_bundle or build / 'runtime-bundle'
        entry = validate(selected, build / (backend + '-worker'), backend == 'glycin')[1]
        require_trial(findings, entry['destination'])
        (trace.parent / (trace.name + '.json')).write_text(json.dumps(findings, indent=2) + '\n')
        return dict(artifact=str(trace.relative_to(root)) + '.json',
                    events=len(findings['events']), successful_execs=findings['successful_execs'])

    def capture(source, record, diagnostic=None, cancel_event=None):
        base = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        main_fd = os.open(source / 'source.svg', os.O_RDONLY | os.O_CLOEXEC)
        trace = source.parent / 'discovery.trace'
        try:
            files = acquire(build, base, main_fd, 'source.svg', evidence=record,
                            trace=trace, diagnostic=diagnostic, cancel_event=cancel_event)
            record['captured_artifacts'] = {}
            for name, data in files.items():
                retained = source.parent / 'captured' / name
                retained.parent.mkdir(parents=True, exist_ok=True)
                retained.write_bytes(data)
                record['captured_artifacts'][str(retained.relative_to(root))] = sha(data)
            return files
        finally:
            require(os.fstat(base) and os.fstat(main_fd), 'caller descriptors closed')
            os.close(main_fd)
            os.close(base)
            if record.get('discovery_cleanup'):
                report['scopes'].append(record['discovery_cleanup'])
            if trace.exists():
                record['discovery_findings'] = trace_evidence(source, trace)

    try:
        report['binaries'] = {name: sha((build / name).read_bytes())
                              for name in ('linked-probe', 'linked-tests', 'qt-worker', 'glycin-worker')}
        def cpp(record):
            result = subprocess.run([str(build / 'linked-tests')], capture_output=True, timeout=30)
            record.update(returncode=result.returncode, stdout=result.stdout.decode(), stderr=result.stderr.decode())
            require(result.returncode == 0, record)
        check('cpp-acquisition', cpp)
        def parent_validation(record):
            rejected = 0
            for paths in (['main.svg'], ['main.svg/x'], ['a', 'a-', 'a/b'], ['../x'], ['/x'],
                          ['a%20b'], ['a?x'], ['a#x'], ['https:x'], ['a\\b'], ['a\x00b'],
                          ['x'] * 257, ['x' * 1025], [str(i) + 'x' * 1000 for i in range(256)]):
                try:
                    validate_paths(paths)
                except ValueError:
                    rejected += 1
                else:
                    raise AssertionError(paths)
            require(validate_paths(['a', 'a', 'child/b']) == ['a', 'child/b'], "acceptance check failed: validate_paths(['a', 'a', 'child/b']) == ['a', 'child/b']")
            record['rejected'] = rejected
        check('untrusted-manifest', parent_validation)
        def unavailable(record):
            source = inputs(record['name'], b'<svg/>')
            base = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            main_fd = os.open(source / 'source.svg', os.O_RDONLY | os.O_CLOEXEC)
            try:
                trace = source.parent / 'enosys.trace'
                result = subprocess.run(['strace', '-e', 'inject=openat2:error=ENOSYS', '-o', str(trace),
                                         str(build / 'linked-probe'), str(base), str(main_fd), 'source.svg'],
                                        pass_fds=(base, main_fd), capture_output=True, timeout=15)
                record.update(returncode=result.returncode, stderr=result.stderr.decode(errors='replace'))
                require(result.returncode != 0 and not result.stdout, 'acceptance check failed: result.returncode != 0 and not result.stdout')
                require('openat2 required' in record['stderr'] and 'ENOSYS (Function not implemented) (INJECTED)' in trace.read_text(), "acceptance check failed: 'openat2 required' in record['stderr'] and 'ENOSYS (Function not implemented) (INJECTED)' in trace.read_text()")
            finally:
                os.close(main_fd)
                os.close(base)
        check('unsupported-openat2', unavailable)
        if not args.focused:
            pixel = bytes([24, 64, 104, 255])
            png = encode([tuple(pixel)], 8, 4, None)
            for case, paths in [('same', ['pixel.png']), ('descendant', ['child/pixel.png']),
                                ('repeated', ['pixel.png', 'child/pixel.png', 'pixel.png'])]:
                for mutation in ('replace', 'remove'):
                    def positive(record, case=case, paths=paths, mutation=mutation):
                        source = inputs(record['name'], svg(paths), png)
                        files = capture(source, record)
                        record['captured_hashes'] = {name: sha(data) for name, data in files.items()}
                        require(set(files) == {'main.svg', *paths}, "acceptance check failed: set(files) == {'main.svg', *paths}")
                        for path in ('source.svg', 'pixel.png', 'child/pixel.png'):
                            if mutation == 'replace':
                                (source / path).write_bytes(b'replaced after capture')
                            else:
                                (source / path).unlink()
                        expected = pixel * len(paths)
                        (source.parent / 'expected.rgba').write_bytes(expected)
                        record['renders'] = []
                        for backend in ('qt', 'glycin'):
                            for repetition in range(3):
                                trial = dict(backend=backend, repetition=repetition)
                                record['renders'].append(trial)
                                trace = source.parent / f'{backend}-{repetition}.trace'
                                worker = Worker(build / (backend + '-worker'), glycin=backend == 'glycin',
                                                captured_files=files, trace=trace)
                                try:
                                    trial['load'] = worker.request('load', files['main.svg'], capsule=True)
                                    decoded = worker.request('svg', capsule=True, width=len(paths), height=1,
                                                             capture_pixels=True)
                                    actual = bytes(decoded.pop('pixels'))
                                    trial['decode'] = decoded
                                    trial.update(expected_sha256=sha(expected), actual_sha256=sha(actual))
                                    (source.parent / f'{backend}-{repetition}.rgba').write_bytes(actual)
                                    require(decoded['outcome'] == 'success' and actual == expected, trial)
                                finally:
                                    trial['stderr'] = worker.close()
                                    trial['cleanup'] = worker.cleanup
                                    report['scopes'].append(worker.cleanup)
                                    trial['findings'] = trace_evidence(source, trace, backend)
                                    require(worker.scope_empty, trial)
                    check(case + '-' + mutation, positive)
            invalid = {
                'external': svg(['https://example.invalid/x']), 'encoded': svg(['pixel%2epng']),
                'absolute': svg(['/pixel.png']), 'traversal': svg(['../pixel.png']),
                'query': svg(['pixel.png?x']), 'fragment': svg(['pixel.png#x']),
                'reserved': svg(['main.svg']), 'prefix': svg(['main.svg/pixel.png']),
                'staging-prefix': svg(['a', 'a/b']),
                'missing': svg(['missing.png']), 'symlink': svg(['link.png']),
                'intermediate-symlink': svg(['alias/pixel.png']),
                'count': svg(['pixel.png'] * 257), 'long-path': svg(['x' * 1025]),
                'xml-base': b'<svg xmlns="http://www.w3.org/2000/svg" xml:base="child/"><image href="pixel.png"/></svg>',
                'css': b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import "x";</style></svg>',
                'entity': b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>',
                'animated-reference': b'<svg><image href="pixel.png"><animate attributeName="href" to="other.png"/></image></svg>',
            }
            for name, document in invalid.items():
                def rejected(record, name=name, document=document):
                    source = inputs(record['name'], document, png)
                    (source / 'link.png').symlink_to('pixel.png')
                    (source / 'alias').symlink_to('child')
                    try:
                        capture(source, record)
                    except (ValueError, RuntimeError):
                        require('identities' not in record, 'partial capsule')
                    else:
                        raise AssertionError('unsupported resource accepted')
                check('reject-' + name, rejected)
            for name in ('main-change', 'main-replace', 'main-delete', 'base-rename', 'cancel'):
                def barrier(record, name=name):
                    source = inputs(record['name'], svg(['pixel.png']), png)
                    event = threading.Event()
                    def diagnostic(phase):
                        record.setdefault('barrier_acknowledgements', []).append(phase)
                        if phase != 'manifest-validated':
                            return
                        if name == 'main-change':
                            (source / 'source.svg').write_bytes(b'changed')
                        elif name == 'main-replace':
                            (source / 'new.svg').write_bytes(svg(['pixel.png']))
                            (source / 'new.svg').replace(source / 'source.svg')
                        elif name == 'main-delete':
                            (source / 'source.svg').unlink()
                        elif name == 'base-rename':
                            source.rename(source.parent / 'pinned')
                            source.mkdir()
                            (source / 'source.svg').write_bytes(b'replacement')
                        else:
                            event.set()
                    try:
                        files = capture(source, record, diagnostic, event)
                    except (RuntimeError, RequestCancelled):
                        require(name != 'base-rename', "acceptance check failed: name != 'base-rename'")
                    else:
                        require(name == 'base-rename' and files['pixel.png'] == png, "acceptance check failed: name == 'base-rename' and files['pixel.png'] == png")
                check('barrier-' + name, barrier)
            # Resource content validation belongs to both isolated renderers, never acquisition.
            for name, resource in [('nested-svg', svg(['pixel.png'])), ('invalid-raster', b'not an image'),
                                   ('animated-raster', base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'))]:
                def content(record, resource=resource):
                    source = inputs(record['name'], svg(['pixel.png']), resource)
                    files = capture(source, record)
                    for backend in ('qt', 'glycin'):
                        trace = source.parent / (backend + '.trace')
                        worker = Worker(build / (backend + '-worker'), glycin=backend == 'glycin',
                                        captured_files=files, trace=trace)
                        try:
                            worker.request('load', files['main.svg'], capsule=True)
                            reply = worker.request('svg', capsule=True)
                            require(reply['outcome'] != 'success', reply)
                        finally:
                            worker.close()
                            report['scopes'].append(worker.cleanup)
                            trace_evidence(source, trace, backend)
                            require(worker.scope_empty, 'scope cleanup unverified')
                check('content-' + name, content)
            # Valid document-local use and embedded raster survive the shared extractor.
            embedded = base64.b64encode(png).decode()
            document = (f'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">'
                        f'<defs><image id="p" width="1" height="1" href="data:image/png;base64,{embedded}"/></defs>'
                        '<use href="#p"/></svg>').encode()
            def self_contained(record):
                source = inputs(record['name'], document)
                files = capture(source, record)
                require(set(files) == {'main.svg'}, "acceptance check failed: set(files) == {'main.svg'}")
                for backend in ('qt', 'glycin'):
                    for repetition in range(3):
                        trace = source.parent / f'{backend}-{repetition}.trace'
                        worker = Worker(build / (backend + '-worker'), glycin=backend == 'glycin',
                                        captured_files=files, trace=trace)
                        try:
                            worker.request('load', files['main.svg'], capsule=True)
                            reply = worker.request('svg', capsule=True, width=1, height=1, capture_pixels=True)
                            actual = bytes(reply.pop('pixels'))
                            record.setdefault('renders', []).append(dict(backend=backend, repetition=repetition,
                                                                        response=reply, actual_sha256=sha(actual),
                                                                        expected_sha256=sha(pixel)))
                            (source.parent / f'{backend}-{repetition}.rgba').write_bytes(actual)
                            (source.parent / 'expected.rgba').write_bytes(pixel)
                            require(reply['outcome'] == 'success' and actual == pixel, reply)
                        finally:
                            worker.close()
                            report['scopes'].append(worker.cleanup)
                            trace_evidence(source, trace, backend)
                            require(worker.scope_empty, 'scope cleanup unverified')
            check('embedded-and-local-fragment', self_contained)
    except Exception as error:
        results.append(dict(name='incomplete', status='failed', error=repr(error)))
    report['fixture_cleanup'] = []
    for path in root.rglob('*'):
        if path.is_symlink() or path.name == 'unreferenced-fifo':
            report['fixture_cleanup'].append(str(path.relative_to(root)))
            path.unlink()
        elif path.name == 'unreadable':
            path.chmod(0o644)
    expected_count = 3 if args.focused else 36
    report['passed'] = (len(results) == expected_count and all(r['status'] == 'passed' for r in results)
                        and all(scope and scope.get('scope_empty') for scope in report['scopes']))
    report['passed'] = invocation.finish(results, legacy=report)
    print(f"{sum(r['status'] == 'passed' for r in results)}/{len(results)} passed; {root / 'report.json'}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(guarded_main(main))
