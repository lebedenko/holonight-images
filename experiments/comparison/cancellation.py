#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Private deterministic cancellation checks; requires real user scope isolation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from unittest.mock import patch

from color import encode
from runtime_evidence import guarded_main, Invocation, destination, require
from runtime_suites import scenarios, requirements

from harness import CleanupError, RequestCancelled, Worker


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    parser.add_argument('--focused', action='store_true', help='hostile peers only')
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--runtime-bundle', type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    root = destination(args, build, 'cancellation-')
    options = dict(focused=args.focused)
    options.update(build=str(build), runtime_bundle=str((args.runtime_bundle or build / 'runtime-bundle').resolve()),
                   evidence_dir=str(root))
    invocation = Invocation(root, 'cancellation', options, scenarios('cancellation', options), requirements('cancellation', options))
    invocation.runtime_bundle = args.runtime_bundle
    results = []
    report = dict(results=results, limitation='Dispatch proves an outstanding request, not codec entry; '
                  'cooperative decoder interruption remains unproven.')

    def run(name, mode=None, phase='dispatched', ack=None, backend=None, loaded=False,
            payload=b'', timeout=False, failure=None):
        record = dict(name=name, markers=[], input_bytes=len(payload),
                      input_sha256=hashlib.sha256(payload).hexdigest())
        if payload:
            (root / (name + '.input')).write_bytes(payload)
        results.append(record)
        invocation.scenario(name)
        event = threading.Event()
        reached = threading.Event()
        controller = None
        worker = None
        armed = False
        reads = 0

        def hook(observed):
            nonlocal reads
            if not armed:
                return
            if observed == 'read-progress':
                reads += 1
            target = observed == phase
            if mode == 'cancel-control' and phase == 'read-progress':
                target = target and reads == 2
            if mode == 'cancel-pixels' and phase == 'read-progress':
                target = target and reads == 3
            if target and not event.is_set():
                record['markers'].append(dict(phase=observed, time=time.monotonic()))
                if ack:
                    deadline = time.monotonic() + 3
                    while ack.encode() not in os.pread(worker.stderr.fileno(), 65536, 0):
                        if time.monotonic() >= deadline:
                            raise AssertionError('missing peer acknowledgement: ' + ack)
                        event.wait(.005)
                    record['markers'].append(dict(ack=ack, time=time.monotonic()))
                reached.set()
                if not event.wait(1):
                    raise AssertionError("cancellation controller did not acknowledge phase")

        try:
            worker = Worker(build / ((backend + '-worker') if backend else 'fault-worker'),
                            glycin=backend == 'glycin', isolated=mode != 'cancel-descendant',
                            arguments=[mode] if mode else (), diagnostic=hook)
            # Leave pre-transfer cancellation unsampled to exercise manager identity resolution.
            deadline = time.monotonic() + 3
            while worker.cgroup is None and phase != 'before-transfer':
                worker.sample()
                if time.monotonic() >= deadline:
                    raise AssertionError('scope startup unavailable')
                event.wait(.005)
            if backend:
                require(worker.request('load', fixture)['outcome'] == 'loaded', "acceptance check failed: worker.request('load', fixture)['outcome'] == 'loaded'")
                if loaded:
                    require(worker.request('decode', width=2, height=1)['bytes'] == 8, "acceptance check failed: worker.request('decode', width=2, height=1)['bytes'] == 8")
            def cancel_from_caller():
                if reached.wait(4):
                    event.set()

            controller = threading.Thread(target=cancel_from_caller)
            controller.start()
            armed = True
            if timeout:
                worker.operation_deadline = time.monotonic() - 1
            try:
                if failure == 'manager':
                    with patch('harness.subprocess.run', side_effect=OSError('controlled manager failure')):
                        worker.request('decode' if backend else 'load', payload, cancel_event=event,
                                       width=2, height=1)
                elif failure == 'budget':
                    real_manager = worker._manager

                    def exhaust(arguments, deadline):
                        return real_manager(arguments, time.monotonic() - 1)
                    with patch.object(worker, '_manager', side_effect=exhaust):
                        worker.request('load', cancel_event=event)
                else:
                    worker.request('decode' if backend else 'load', payload, cancel_event=event,
                                   width=2, height=1)
            except (RequestCancelled, CleanupError) as error:
                record.update(exception=type(error).__name__, detail=str(error),
                              request_returned=time.monotonic())
                require(isinstance(error, CleanupError) == bool(failure), str(error))
            else:
                raise AssertionError('cancelled request returned a result')
            require(event.is_set(), 'cancellation phase missing')
            if not failure:
                require(worker.scope_empty and worker.process.poll() is not None, 'acceptance check failed: worker.scope_empty and worker.process.poll() is not None')
                require(worker.cleanup['completed'] - worker.cancel_observed <= 5, "acceptance check failed: worker.cleanup['completed'] - worker.cancel_observed <= 5")
                if mode == 'cancel-descendant':
                    require(any('--signal=KILL' in entry['arguments']
                               for entry in worker.cleanup['manager']), 'scope KILL not exercised')
                before = dict(worker.cleanup)
                worker.abort()
                require(worker.cleanup == before, 'repeated teardown changed evidence')
            try:
                worker.request('load')
            except RuntimeError as error:
                require('terminal worker' in str(error), "acceptance check failed: 'terminal worker' in str(error)")
            else:
                raise AssertionError('terminal worker reused')
            if failure:
                before = dict(worker.cleanup)
                try:
                    worker.abort()
                except CleanupError:
                    pass
                else:
                    raise AssertionError('failed cleanup retry was accepted')
                require(worker.cleanup == before, 'acceptance check failed: worker.cleanup == before')
            record['status'] = 'passed'
        except Exception as error:
            record.update(status='failed', error=repr(error))
        finally:
            if controller:
                reached.set()
                controller.join(timeout=1)
            if worker:
                record['cleanup'] = worker.cleanup
                record['cancel_observed'] = getattr(worker, 'cancel_observed', None)
                if failure:
                    # Controlled boundary failure leaves a real scope: recover explicitly for test hygiene.
                    # This is a test-only reset, never an automatic harness retry.
                    worker.cleanup = None
                    worker._cleanup_error = None
                    try:
                        worker.abort()
                        record['test_scope_recovery'] = worker.cleanup
                    except Exception as error:
                        record.update(status='failed', recovery_error=repr(error))
                try:
                    record['stderr'] = worker.close()
                    require(worker.scope_empty, 'acceptance check failed: worker.scope_empty')
                    worker.close()
                except Exception as error:
                    record.update(status='failed', close_error=repr(error))
        if backend and record.get('status') == 'passed':
            recovery = Worker(build / (backend + '-worker'), glycin=backend == 'glycin')
            try:
                completed_event = threading.Event()
                require(recovery.request('load', fixture, cancel_event=completed_event)['outcome'] == 'loaded', "acceptance check failed: recovery.request('load', fixture, cancel_event=completed_event)['outcome'] == 'loaded'")
                completed_event.set()
                require(not recovery.terminal, 'late cancellation affected completed request')
                decoded = recovery.request('decode', width=2, height=1, capture_pixels=True)
                require(bytes(decoded['pixels']) == expected, "acceptance check failed: bytes(decoded['pixels']) == expected")
                record['recovery_pixels_sha256'] = hashlib.sha256(bytes(decoded['pixels'])).hexdigest()
            except Exception as error:
                record.update(status='failed', recovery_error=repr(error))
            finally:
                try:
                    record['recovery_stderr'] = recovery.close()
                    record['recovery_cleanup'] = recovery.cleanup
                    require(recovery.scope_empty, 'acceptance check failed: recovery.scope_empty')
                except Exception as error:
                    record.update(status='failed', recovery_close_error=repr(error))
        invocation.checkpoint()

    fixture = b''
    expected = bytes([24, 64, 104, 255, 144, 184, 224, 255])
    try:
        report['binaries'] = {name: digest(build / name) for name in
                              ('fault-worker', 'capture-probe', 'qt-worker', 'glycin-worker')}
        run('before-transfer', 'cancel-await', 'before-transfer')
        run('blocked-input', 'cancel-input', 'blocked-write', 'ACK blocked-input', payload=b'x' * (1024 * 1024))
        run('await-response', 'cancel-await', 'dispatched', 'ACK dispatched')
        run('partial-control', 'cancel-control', 'read-progress', 'ACK partial-control')
        run('partial-pixels', 'cancel-pixels', 'read-progress', 'ACK partial-pixels')
        run('term-resistant-descendant', 'cancel-descendant', 'dispatched', 'ACK descendant-ready')
        run('eof-race', 'cancel-eof', 'request-error')
        run('malformed-race', 'cancel-malformed', 'request-error')
        run('timeout-race', 'cancel-await', 'request-error', timeout=True)
        run('manager-failure', 'cancel-await', failure='manager')
        run('exhausted-budget', 'cancel-await', failure='budget')
        if not args.focused:
            source = root / 'fixture.png'
            source.write_bytes(encode([(24, 64, 104, 255), (144, 184, 224, 255)], 8, 4, None))
            probe = subprocess.run([str(build / 'capture-probe'), str(source), str(source.stat().st_size)],
                                   capture_output=True, timeout=15, check=True)
            fixture = probe.stdout
            require(fixture == source.read_bytes(), 'acceptance check failed: fixture == source.read_bytes()')
            report['fixture_sha256'] = hashlib.sha256(fixture).hexdigest()
            (root / 'captured.png').write_bytes(fixture)
            for backend in ('qt', 'glycin'):
                for loaded in (False, True):
                    for phase in ('dispatched', 'before-result'):
                        for repetition in range(3):
                            run(f'{backend}-{loaded}-{phase}-{repetition}', backend=backend,
                                phase=phase, loaded=loaded)
    except Exception as error:
        results.append(dict(name='incomplete', status='failed', error=repr(error)))
    required = 11 if args.focused else 35
    report['passed'] = len(results) == required and all(r['status'] == 'passed' for r in results)
    report['passed'] = invocation.finish(results, legacy=report)
    print(f"{sum(r['status'] == 'passed' for r in results)}/{required} passed; {root / 'report.json'}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(guarded_main(main))
