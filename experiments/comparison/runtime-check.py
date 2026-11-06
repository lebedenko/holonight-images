#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fresh private runtime acceptance with independently validated child evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from unittest.mock import patch

from color import encode
from harness import Worker
from linked import acquire
from runtime_bundle import MANIFEST, digest, host_environment, validate, prepare
from runtime_controls import CHANNELS, Controls
from runtime_evidence import guarded_main, Invocation, destination, require, validate_child, validate_report
from runtime_suites import scenarios, requirements as suite_requirements
from runtime_trace import analyze, require_trial, require_failure

SUITES = [('cancellation.py', 'cancellation', {'focused': False}, []),
          ('capture.py', 'capture', {}, []), ('linked-check.py', 'linked', {'focused': False}, []),
          ('check.py', 'check', {'filter': 'protocol'}, ['--filter', 'protocol']),
          ('check.py', 'check', {'filter': 'capsule'}, ['--filter', 'capsule'])]


def contract(regressions):
    needed = {}
    for channel in CHANNELS:
        for broken in (False, True):
            name = ('broken-' if broken else 'control-') + channel
            needed[name] = dict(artifacts=[name + '.json'], min_scopes=1, scopes=[])
    needed['isolated-discovery'] = dict(artifacts=['isolated-discovery.trace', 'isolated-discovery.json'], min_scopes=1, scopes=[])
    for backend in ('qt', 'glycin'):
        for kind in ('png', 'linked'):
            for n in range(3):
                name = f'{backend}-{kind}-{n}'
                artifacts = [name + '.trace', name + '.rgba', name + '-findings.json', 'input.png', MANIFEST]
                if kind == 'linked':
                    artifacts += [name + '-discovery.trace', name + '-discovery.json']
                needed[name] = dict(artifacts=artifacts, min_scopes=2 if kind == 'linked' else 1, scopes=[])
    for name in ('host-file-network-denied', 'partial-constructor-cleanup'):
        needed[name] = dict(artifacts=['denied.trace'] if name == 'host-file-network-denied' else [], min_scopes=1, scopes=[])
    for stage in ('outer', 'nested'):
        for kind in ('failed', 'missing'):
            name = f'{stage}-{kind}-sandbox'
            needed[name] = dict(artifacts=[name + '.trace', name + '.json'], min_scopes=1, scopes=[])
    for kind in ('missing', 'invalid'):
        needed['preflight-' + kind] = dict(artifacts=[], min_scopes=0, scopes=[])
    if regressions:
        for index, (script, _, _, _) in enumerate(SUITES):
            name = f'regression-{index}-{script}'
            needed[name] = dict(artifacts=[name + '/report.json', name + '.stdout', name + '.stderr'], min_scopes=0, scopes=[])
    return needed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('--regressions', action='store_true')
    parser.add_argument('--evidence-dir', type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    root = destination(args, build, 'runtime-evidence-')
    needed = contract(args.regressions)
    options = dict(regressions=args.regressions, build=str(build), evidence_dir=str(root))
    invocation = Invocation(root, 'runtime', options, needed, needed)
    records = invocation.report['records']
    print(root, flush=True)

    def check(name, action):
        invocation.scenario(name)
        record = dict(name=name, status='failed')
        records.append(record)
        invocation.checkpoint()
        try:
            action(record)
            record['status'] = 'passed'
        except Exception as error:
            record['error'] = repr(error)
        invocation.checkpoint()
        print(name + ': ' + record['status'] + (' ' + record['error'] if 'error' in record else ''), flush=True)

    try:
        controls = Controls(build, root)
        bundle = root / 'runtime-bundle'
        prepare(build, bundle, [(controls.root / 'adjacent/runtime-diagnostic', 'qt')])
        invocation.runtime_bundle = bundle
        shutil.copyfile(bundle / MANIFEST, root / MANIFEST)
        invocation.report['sources'] = {p.name: digest(p) for p in Path(__file__).parent.glob('*') if p.is_file()}
        poisoned = controls.poisoned()
        png = encode([(24, 64, 104, 255)], 8, 4, None)
        (root / 'input.png').write_bytes(png)
        invocation.checkpoint()
    except Exception as error:
        invocation.report['prerequisite_error'] = repr(error)
        invocation.finish(records)
        return 1

    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        server.listen(128)
        for channel in CHANNELS:
            for broken in (False, True):
                check(('broken-' if broken else 'control-') + channel,
                      lambda r, channel=channel, broken=broken: controls.run(r, channel, broken=broken, port=server.getsockname()[1]))

    def isolated_discovery(record):
        binary = controls.root / 'adjacent/runtime-diagnostic'
        with patch.dict(os.environ, poisoned):
            worker = Worker(binary, trace=root / 'isolated-discovery.trace')
            try:
                result = worker.request('diagnostic')
                record['response'] = result
            finally:
                record['stderr'] = worker.close()
        require(result.get('outcome') == 'diagnostic', result)
        require(not any(result.get(key) for key in ('path_token', 'library_token', 'plugin_pixel',
                                                   'configuration_token', 'glycin_loader')), result)
        require(not any(value in result['environment'].values() for value in poisoned.values()), result)
        require('HN_' not in json.dumps(result) + record['stderr'], result)
        findings = analyze((root / 'isolated-discovery.trace').read_text(), cwd=str(Path.cwd()), protected=[controls.root])
        require_trial(findings, validate(bundle, binary)[1]['destination'])
        record['findings'] = findings
        (root / 'isolated-discovery.json').write_text(json.dumps(record, indent=2) + '\n')
    check('isolated-discovery', isolated_discovery)

    def trial(record, backend, linked=False):
        trace = root / (record['name'] + '.trace')
        binary = build / (backend + '-worker')
        manifest, entry = validate(bundle, binary, backend == 'glycin')
        record.update(binary_sha256=digest(binary), manifest_sha256=digest(bundle / MANIFEST),
                      input_sha256=digest(root / 'input.png'))
        files = None
        if linked:
            source = root / (record['name'] + '-source')
            source.mkdir()
            (source / 'pixel.png').write_bytes(png)
            (source / 'main.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" '
                'xmlns:xlink="http://www.w3.org/1999/xlink" width="1" height="1">'
                '<image width="1" height="1" xlink:href="pixel.png"/></svg>')
            base = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
            main_fd = os.open(source / 'main.svg', os.O_RDONLY)
            try:
                record['acquisition'] = {}
                files = acquire(build, base, main_fd, 'main.svg', evidence=record['acquisition'], trace=root / (record['name'] + '-discovery.trace'))
            finally:
                os.close(main_fd)
                os.close(base)
            record['captured_hashes'] = {name: hashlib.sha256(data).hexdigest()
                                         for name, data in files.items()}
            (source / 'pixel.png').write_bytes(b'replaced')
        with patch.dict(os.environ, poisoned):
            worker = Worker(binary, glycin=backend == 'glycin', trace=trace, captured_files=files, runtime_bundle=bundle)
            record['command'] = worker.launch_command
            record['runtime_command'] = worker.runtime_command
            try:
                record['load'] = worker.request('load', files['main.svg'] if linked else png, capsule=linked)
                result = worker.request('svg' if linked else 'decode', width=1, height=1,
                                        capture_pixels=True, **({'capsule': True} if linked else {}))
                pixels = bytes(result.pop('pixels'))
                record['result'] = result
                (root / (record['name'] + '.rgba')).write_bytes(pixels)
                if not (pixels == bytes([24, 64, 104, 255])):
                    raise AssertionError(result)
                record['memory_max'] = (worker.cgroup / 'memory.max').read_text().strip()
                record['swap_max'] = (worker.cgroup / 'memory.swap.max').read_text().strip()
                if not (record['memory_max'] == str(2 * 1024**3) and record['swap_max'] == '0'):
                    raise AssertionError("acceptance check failed: record['memory_max'] == str(2 * 1024**3) and record['swap_max'] == '0'")
            finally:
                record['stderr'] = worker.close()
                record['cleanup'] = worker.cleanup
                if not (worker.scope_empty):
                    raise AssertionError('acceptance check failed: worker.scope_empty')
        protected = [controls.root] + ([source] if linked else [])
        findings = analyze(trace.read_text(), cwd=str(Path.cwd()), protected=protected)
        loader = '/usr/lib/glycin-loaders/2+/' + ('glycin-svg' if linked else 'glycin-image-rs') if backend == 'glycin' else None
        require_trial(findings, entry['destination'], loader)
        record['findings'] = dict(artifact=record['name'] + '-findings.json', successful_execs=findings['successful_execs'])
        (root / (record['name'] + '-findings.json')).write_text(json.dumps(findings, indent=2) + '\n')
        if linked:
            discovery = analyze((root / (record['name'] + '-discovery.trace')).read_text(),
                                cwd=str(Path.cwd()), protected=protected)
            require_trial(discovery, validate(bundle, build / 'qt-worker')[1]['destination'])
            (root / (record['name'] + '-discovery.json')).write_text(json.dumps(discovery, indent=2) + '\n')
            record['discovery_findings'] = dict(artifact=record['name'] + '-discovery.json')

    for backend in ('qt', 'glycin'):
        for linked in (False, True):
            for n in range(3):
                check(f'{backend}-{"linked" if linked else "png"}-{n}',
                      lambda r, backend=backend, linked=linked: trial(r, backend, linked))

    def denied(record):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            worker = Worker(build / 'fault-worker', arguments=['probe', controls.root / 'host-file', server.getsockname()[1]],
                            trace=root / 'denied.trace')
            try:
                record['result'] = worker.request('probe')
                require(record['result']['original_readable'] is False, record)
                require(record['result']['host_network_reachable'] is False, record)
            finally:
                worker.abort()
                record['stderr'] = worker.close()
            record['findings'] = analyze((root / 'denied.trace').read_text(), cwd=str(Path.cwd()), protected=[controls.root])
            require(not record['findings']['protected_operations'], record)
            require(any(e['classification'] == 'network-failed' for e in record['findings']['events']), record)
    check('host-file-network-denied', denied)

    def failed_launch(record, stage, kind):
        selected = bundle
        replacement = '/usr/bin/false' if kind == 'failed' else '/missing-bwrap'
        if stage == 'nested':
            selected = root / (record['name'] + '-bundle')
            shutil.copytree(bundle, selected, copy_function=os.link)
            target = selected / 'usr/bin/bwrap'
            target.unlink()
            target.write_bytes(b'#!/missing-interpreter\n' if kind == 'missing' else Path('/usr/bin/false').read_bytes())
            target.chmod(0o755)
            manifest = json.loads((selected / MANIFEST).read_text())
            for item in manifest['files']:
                if item['destination'] == '/usr/bin/bwrap':
                    item.update(size=target.stat().st_size, sha256=digest(target))
            (selected / MANIFEST).unlink()
            (selected / MANIFEST).write_text(json.dumps(manifest))
            replacement = '/usr/bin/bwrap'
            record['replacement_sha256'] = digest(target)
        else:
            record['replacement_sha256'] = digest(Path(replacement)) if kind == 'failed' else None
        record.update(injection=dict(stage=stage, kind=kind, replacement=replacement))
        worker = Worker(build / 'glycin-worker', glycin=True, runtime_bundle=selected,
                        sandbox_executable=replacement if stage == 'outer' else '/usr/bin/bwrap',
                        trace=root / (record['name'] + '.trace'))
        try:
            try:
                record['load'] = worker.request('load', png)
            except (RuntimeError, BrokenPipeError) as error:
                record['request_error'] = repr(error)
        finally:
            worker.abort()
            record['stderr'] = worker.close()
        findings = analyze((root / (record['name'] + '.trace')).read_text(), cwd=str(Path.cwd()))
        diagnostic = record['stderr'] + json.dumps(record.get('load', {}))
        record['contract'] = require_failure(findings, stage=stage, kind=kind,
            worker=validate(selected, build / 'glycin-worker', True)[1]['destination'],
            replacement=replacement, diagnostic=diagnostic, load=record.get('load'), status=worker.process.returncode)
        record['findings'] = findings
        (root / (record['name'] + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    for stage in ('outer', 'nested'):
        for kind in ('failed', 'missing'):
            check(f'{stage}-{kind}-sandbox', lambda r, stage=stage, kind=kind: failed_launch(r, stage, kind))

    def partial_constructor(record):
        worker = Worker.__new__(Worker)
        with patch('harness.os.set_blocking', side_effect=OSError('injected pipe setup failure')):
            try:
                worker.__init__(build / 'qt-worker')
            except OSError as error:
                record['expected_error'] = str(error)
            else:
                raise ValueError('partial constructor failure ignored')
        record['cleanup'] = worker.cleanup
        require(worker.scope_empty and worker.process.poll() is not None, record)
        require(worker.stderr.closed and worker.process.stdin.closed and worker.process.stdout.closed, record)
    check('partial-constructor-cleanup', partial_constructor)

    def preflight(record, kind):
        with patch('harness.subprocess.Popen') as popen:
            try:
                Worker(build / 'qt-worker', runtime_bundle=root / ('missing' if kind == 'missing' else 'input.png'))
            except ValueError as error:
                record['expected_error'] = str(error)
            else:
                raise ValueError('preflight accepted invalid bundle')
            require(not popen.called, 'preflight launched scope')
    for kind in ('missing', 'invalid'):
        check('preflight-' + kind, lambda r, kind=kind: preflight(r, kind))

    if args.regressions and any(record['status'] != 'passed' for record in records):
        for index, (script, _, _, _) in enumerate(SUITES):
            records.append(dict(name=f'regression-{index}-{script}', status='failed',
                                error='not run: required runtime scenario failed'))
        invocation.finish(records)
        return 1

    if args.regressions:
        def regression(record, script, suite, child_options, flags):
            child_root = root / record['name']
            child_options = dict(child_options, build=str(build), runtime_bundle=str(bundle), evidence_dir=str(child_root))
            command = ['/usr/bin/python3', str(Path(__file__).parent / script), str(build), *flags,
                       '--runtime-bundle', str(bundle), '--evidence-dir', str(child_root)]
            record.update(command=command, environment=host_environment(), script_sha256=digest(Path(__file__).parent / script))
            result = subprocess.run(command, env=host_environment(), capture_output=True, timeout=300)
            (root / (record['name'] + '.stdout')).write_bytes(result.stdout)
            (root / (record['name'] + '.stderr')).write_bytes(result.stderr)
            record['returncode'] = result.returncode
            require(result.returncode == 0, result.stderr.decode(errors='replace') + result.stdout.decode(errors='replace'))
            child = validate_child(child_root, suite=suite, options=child_options,
                                   required=scenarios(suite, child_options), requirements=suite_requirements(suite, child_options))
            record['child_report_sha256'] = digest(child_root / 'report.json')
            record['child_scenarios'] = len(child['records'])
        for index, (script, suite, child_options, flags) in enumerate(SUITES):
            check(f'regression-{index}-{script}', lambda r, script=script, suite=suite, child_options=child_options, flags=flags:
                  regression(r, script, suite, child_options, flags))
    passed = invocation.finish(records)
    if passed:
        reopened = json.loads((root / 'report.json').read_text())
        validate_report(root, reopened, needed, suite='runtime', options=options, requirements=needed)
        if args.regressions:
            for index, (script, suite, child_options, _) in enumerate(SUITES):
                child_root = root / f'regression-{index}-{script}'
                expected_options = dict(child_options, build=str(build), runtime_bundle=str(bundle), evidence_dir=str(child_root))
                validate_child(child_root, suite=suite, options=expected_options,
                               required=scenarios(suite, expected_options), requirements=suite_requirements(suite, expected_options))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(guarded_main(main))
