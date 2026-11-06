#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded C++ acquisition and source-independent isolated decoding regression."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from color import encode
from geometry import fixtures, expected_pixels
from harness import INPUT_LIMIT, Worker


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    build = parser.parse_args().build.resolve()
    root = Path(tempfile.mkdtemp(prefix='capture-', dir=build))
    results = []
    report = dict(results=results)
    try:
        report['binaries'] = {name: sha((build / name).read_bytes())
                              for name in ('capture-probe', 'qt-worker', 'glycin-worker')}
        source, images = fixtures(root / 'fixtures')
        jpeg = next(data for name, data, _ in images if name == 'II6')
        width, height, jpeg_pixels = expected_pixels(source, 6)
        samples = [(24, 64, 104, 255), (144, 184, 224, 255)]
        png = encode(samples, 8, 4, None)
        svg = (b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="1">'
               b'<rect width="2" height="1" fill="#184068"/></svg>')
        cases = [('png', png, 2, 1, bytes(sum((list(p) for p in samples), [])), 'decode'),
                 ('jpeg', jpeg, width, height, jpeg_pixels, 'decode'),
                 ('svg', svg, 2, 1, bytes([24, 64, 104, 255] * 2), 'svg')]
        for name, fixture, width, height, expected, operation in cases:
            (root / (name + '-expected.rgba')).write_bytes(expected)
            for mutation in ('replace', 'remove'):
                path = root / ('source-' + mutation + '.' + name)
                path.write_bytes(fixture)
                probe = subprocess.run([str(build / 'capture-probe'), str(path), str(len(fixture))],
                                       capture_output=True, timeout=15)
                captured = probe.stdout
                acquisition = dict(name=name, mutation=mutation, returncode=probe.returncode,
                                   stderr=probe.stderr.decode(errors='replace'),
                                   fixture_sha256=sha(fixture), capture_sha256=sha(captured), bytes=len(captured))
                report.setdefault('captures', []).append(acquisition)
                assert probe.returncode == 0 and captured == fixture, acquisition
                (root / (name + '-' + mutation + '-captured.bin')).write_bytes(captured)
                if mutation == 'replace':
                    path.write_bytes(b'replaced after capture')
                else:
                    path.unlink()
                for backend in ('qt', 'glycin'):
                    record = dict(name=f'{backend}-{name}-{mutation}', responses=[])
                    results.append(record)
                    worker = None
                    try:
                        worker = Worker(build / (backend + '-worker'), glycin=backend == 'glycin')
                        observations = []
                        for payload in (fixture, captured):
                            loaded = worker.request('load', payload)
                            inspected = worker.request('inspect')
                            decoded = worker.request(operation, width=width, height=height, capture_pixels=True)
                            pixels = bytes(decoded.pop('pixels'))
                            record['responses'].append(dict(load=loaded, inspect=inspected, decode=decoded))
                            assert loaded['outcome'] == 'loaded', loaded
                            assert inspected['outcome'] in (0, 'loaded', 'success'), inspected
                            assert decoded['outcome'] in (0, 'success'), decoded
                            assert (decoded['width'], decoded['height']) == (width, height), decoded
                            assert len(pixels) == len(expected), decoded
                            assert all(abs(a-b) <= (2 if name == 'jpeg' and i % 4 != 3 else 0)
                                       for i, (a, b) in enumerate(zip(pixels, expected))), decoded
                            observations.append((inspected, decoded, pixels))
                        assert observations[0] == observations[1], 'capture changed inspection or pixels'
                        (root / (record['name'] + '.rgba')).write_bytes(observations[-1][2])
                        record['status'] = 'passed'
                    except Exception as error:
                        record.update(status='failed', error=str(error))
                    finally:
                        if worker:
                            record['stderr'] = worker.close()
                            record['scope_empty'] = worker.scope_empty
                            if not worker.scope_empty:
                                record.update(status='failed', cleanup_error='scope not empty or unverified')
        path = root / 'overflow.bin'
        path.write_bytes(b'ab')
        for limit in (1, 0, -1, INPUT_LIMIT + 1):
            probe = subprocess.run([str(build / 'capture-probe'), str(path), str(limit)],
                                   capture_output=True, timeout=15)
            result = dict(name=f'probe-limit-{limit}', returncode=probe.returncode,
                          stderr=probe.stderr.decode(errors='replace'), output_bytes=len(probe.stdout))
            result['status'] = 'passed' if probe.returncode != 0 and not probe.stdout else 'failed'
            results.append(result)
    except Exception as error:
        results.append(dict(name='incomplete', status='failed', error=str(error)))
    report['hashes'] = {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    report['passed'] = len(results) == 16 and all(r['status'] == 'passed' for r in results)
    (root / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f"{sum(r['status'] == 'passed' for r in results)}/16 passed; {root / 'report.json'}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
