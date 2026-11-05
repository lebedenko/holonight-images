#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent orientation pixels and intrinsic GIF loop qualification; no benchmarks."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
from harness import Worker
from color import profiles, encode, reference


def fixtures(root):
    root.mkdir(parents=True, exist_ok=True)
    values = (24, 64, 104, 144, 184, 224)
    source = bytes(values[(y // 8) * 3 + x // 8] for y in range(16) for x in range(24))
    (root / 'source.pgm').write_bytes(b'P5\n24 16\n255\n' + source)
    jpeg = subprocess.check_output(['cjpeg', '-quality', '100', '-grayscale', str(root / 'source.pgm')])
    images = [('untagged', jpeg, 1)]
    for endian, order in (('<', b'II'), ('>', b'MM')):
        for orientation in range(1, 9):
            tiff = order + struct.pack(endian + 'HIH', 42, 8, 1)
            tiff += struct.pack(endian + 'HHI', 0x112, 3, 1) + struct.pack(endian + 'H', orientation) + b'\0\0' + b'\0' * 4
            app = b'Exif\0\0' + tiff
            images.append((order.decode() + str(orientation), jpeg[:2] + b'\xff\xe1' + struct.pack('>H', len(app) + 2) + app + jpeg[2:], orientation))
    for name, data, _ in images:
        (root / (name + '.jpg')).write_bytes(data)
    return source, images


def expected_pixels(source, orientation):
    width, height = (16, 24) if orientation >= 5 else (24, 16)
    result = bytearray(width * height * 4)
    for y in range(16):
        for x in range(24):
            # Explicit stored-to-display coordinate mappings from EXIF's eight positions.
            dx, dy = {1:(x,y), 2:(23-x,y), 3:(23-x,15-y), 4:(x,15-y),
                      5:(y,x), 6:(15-y,x), 7:(15-y,23-x), 8:(y,23-x)}[orientation]
            offset = (dy * width + dx) * 4
            v = source[y * 24 + x]
            result[offset:offset+4] = bytes((v,v,v,255))
    return width, height, bytes(result)


def application(identifier, repeat):
    return b'\x21\xff\x0b' + identifier + b'\x03\x01' + struct.pack('<H', repeat) + b'\0'


def gif_data(extension=b'', local=False):
    header = b'GIF89a\x02\0\x01\0\x80\0\0' + b'\0\0\0\xff\xff\xff'
    # Literal LZW streams: clear, pixel, clear, pixel, end (all 3-bit codes).
    frames = b''
    for delay, color in ((3, 0), (7, 1)):
        codes = [4, color, 4, color, 5]
        packed = sum(code << (3*i) for i, code in enumerate(codes)).to_bytes(2, 'little')
        frames += b'\x21\xf9\x04\0' + struct.pack('<H', delay) + b'\0\0'
        frames += b'\x2c\0\0\0\0\x02\0\x01\0' + (b'\x80' if local else b'\0')
        if local:
            frames += b'\0\0\0\xff\xff\xff'
        frames += b'\x02\x02' + packed + b'\0'
    return header + extension + frames + b'\x3b'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    root = build / 'geometry'
    source, images = fixtures(root)
    results = []
    profile = profiles(root)['linear-p3']
    samples = [(204,51,13,128), (25,102,178,255), (255,0,0,0)]
    color_data = encode(samples, 8, 4, profile)
    color_expected = reference(samples, 8, 4, 'linear-p3')
    (root / 'policy-color.png').write_bytes(color_data)

    def run(name, action):
        records = []
        try:
            action(records)
            result = dict(name=name, status='passed', records=records)
        except (AssertionError, OSError, RuntimeError, ValueError, TimeoutError) as error:
            result = dict(name=name, status='failed', error=str(error), records=records)
        results.append(result)

    for backend in ('direct', 'qt', 'glycin'):
        worker = Worker(build / ('glycin-worker' if backend == 'glycin' else 'qt-worker'),
                        isolated=backend != 'direct', glycin=backend == 'glycin')
        try:
            for name, data, orientation in images:
                for ignore in (False, True):
                    label = f'{backend}-{name}-' + ('Ignore' if ignore else 'Apply')
                    def geometry(records, data=data, orientation=orientation, ignore=ignore, label=label):
                        records.append(worker.request('load', data, ignore_orientation=ignore))
                        width, height, expected = expected_pixels(source, 1 if ignore else orientation)
                        (root / (label + '-expected.rgba')).write_bytes(expected)
                        for op in ('inspect', 'inspect', 'decode', 'restart', 'inspect', 'decode'):
                            r = worker.request(op, width=24, height=24, capture_pixels=True)
                            pixels = bytes(r.pop('pixels'))
                            records.append(r)
                            for key, value in dict(source_width=24, source_height=16, oriented_width=width,
                                                   oriented_height=height, orientation=orientation,
                                                   orientation_policy='Ignore' if ignore else 'Apply').items():
                                assert r.get(key) == value, (key, value, r)
                            if op == 'decode':
                                assert (r['width'], r['height']) == (width, height), r
                                (root / (label + '-actual.rgba')).write_bytes(pixels)
                                assert len(pixels) == len(expected)
                                differences = bytes(abs(a-b) for a,b in zip(pixels, expected))
                                (root / (label + '-difference.rgba')).write_bytes(differences)
                                assert all(d <= (0 if i % 4 == 3 else 2) for i,d in enumerate(differences)), r
                        for bound in (12, 64):
                            worker.request('restart')
                            r = worker.request('decode', width=bound, height=bound)
                            records.append(r)
                            assert (r['width'], r['height']) == ((width//2,height//2) if bound == 12 else (width,height)), r
                        r = worker.request('decode', ignore_orientation=not ignore)
                        records.append(r)
                        assert r['outcome'] == 'orientation-policy-conflict', r
                    run(label, geometry)

            for ignore in (False, True):
                def policy_color(records, ignore=ignore):
                    records.append(worker.request('load', color_data, ignore_orientation=ignore))
                    r = worker.request('decode', width=3, height=1, capture_pixels=True)
                    records.append(r)
                    assert len(r['pixels']) == len(color_expected), r
                    assert all(abs(a-b) <= (1 if i%4 == 3 else 2)
                               for i,(a,b) in enumerate(zip(r['pixels'], color_expected))), r
                run(backend + '-color-' + ('Ignore' if ignore else 'Apply'), policy_color)

            valid = [('none', b'', None, False)]
            for identifier in (b'NETSCAPE2.0', b'ANIMEXTS1.0'):
                for repeat in (0, 1, 2, 65535):
                    valid.append((identifier.decode() + str(repeat), application(identifier, repeat), repeat, False))
            valid += [('duplicate-local-unrelated', application(b'NETSCAPE2.0', 2)*2 + b'\x21\xfe\x03abc\0', 2, True)]
            for name, extension, repeat, local in valid:
                data = gif_data(extension, local)
                (root / (name + '.gif')).write_bytes(data)
                def valid_gif(records, data=data, repeat=repeat):
                    loaded = worker.request('load', data)
                    records.append(loaded)
                    fact = loaded['intrinsic_loop']
                    assert fact == dict(provenance='supplemental-gif-block-reader', scan_status='complete',
                                        raw_declaration=repeat, total_plays=None if repeat == 0 else 1 if repeat is None else repeat+1,
                                        infinite=repeat == 0), fact
                    if backend != 'glycin':
                        records.append(worker.request('gif-open'))
                        assert 'loop_count' in records[-1]
                    for cycle in range(2):
                        if cycle:
                            restarted = worker.request('restart')
                            records.append(restarted)
                            assert restarted['intrinsic_loop'] == fact
                        for color, delay in ((0,30),(255,70)):
                            r = worker.request('frame', width=2, height=1, capture_pixels=True)
                            records.append(r)
                            assert r['pixels'] == [color,color,color,255]*2, r
                            assert r.get('delay_ms', r.get('delay_us',0)/1000) == delay, r
                        r = worker.request('frame')
                        records.append(r)
                        assert r['outcome'] == 'end', r
                run(backend + '-gif-' + name, valid_gif)

            good = gif_data(application(b'NETSCAPE2.0', 1))
            bad = [('header', good[:5]), ('screen', good[:10]), ('global-table', good[:15]),
                   ('subblock', good[:35]), ('trailer', good[:-1]),
                   ('local-table', gif_data(local=True)[:40]),
                   ('conflict', gif_data(application(b'NETSCAPE2.0',1)+application(b'ANIMEXTS1.0',2))),
                   ('block-budget', gif_data(b'\x21\xfe\x01a\0'*22000)),
                   ('extension-budget', gif_data(b'\x21\xfe'+(b'\xff'+b'a'*255)*4113+b'\0'))]
            for name, data in bad:
                (root / ('bad-' + name + '.gif')).write_bytes(data)
                def malformed(records, data=data, name=name):
                    records.append(worker.request('load', data))
                    scan = worker.request('gif-scan')
                    records.append(scan)
                    fact = scan['intrinsic_loop']
                    assert fact['scan_status'] == 'unavailable' and fact.get('reason'), fact
                    assert fact['total_plays'] is None and fact['infinite'] is None, fact
                    reasons = {'header':'header', 'screen':'logical-screen-descriptor',
                               'global-table':'global-color-table', 'subblock':'subblock-payload',
                               'trailer':'missing-trailer', 'local-table':'local-color-table',
                               'conflict':'conflicting-declarations', 'block-budget':'block-budget',
                               'extension-budget':'extension-budget'}
                    assert fact['reason'] == reasons[name], fact
                    # Observe decoding independently; parser rejection need not imply decoder rejection.
                    records.append(worker.request('decode', width=2, height=1))
                run(backend + '-scan-' + name, malformed)
        finally:
            results.append(dict(name=backend + '-diagnostics', status='observed', stderr=worker.close()))
    destination = build / 'geometry.json'
    if destination.exists():
        shutil.copy2(destination, build / ('geometry-' + hashlib.sha256(destination.read_bytes()).hexdigest()[:12] + '.json'))
    report = dict(
        expected_gif_frames=[[0,0,0,255]*2, [255,255,255,255]*2],
        expected_gif_delays_ms=[30,70], expected_policy_color=color_expected, results=results,
        binaries={p:hashlib.sha256((build / p).read_bytes()).hexdigest()
                  for p in ('qt-worker','glycin-worker')},
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.iterdir() if p.is_file()},
    )
    destination.write_text(json.dumps(report, indent=2) + '\n')
    failed = [r for r in results if r['status'] == 'failed']
    for result in failed:
        print(result['name'], result['error'])
    print(f'{len(results)-len(failed)-3} passed; {len(failed)} failed; {destination}')
    return bool(failed)


if __name__ == '__main__':
    raise SystemExit(main())
