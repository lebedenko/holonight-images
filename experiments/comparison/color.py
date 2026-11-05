#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent PNG writer and analytical SDR reference; no candidate encoding/conversion."""
import argparse
import ctypes as C
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import zlib

from harness import Worker


class XY(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double), ('Y', C.c_double)]


class Primaries(C.Structure):
    _fields_ = [('r', XY), ('g', XY), ('b', XY)]


def profiles(root):
    cms = C.CDLL('liblcms2.so.2')
    for name, args, result in (
        ('cmsBuildGamma', [C.c_void_p, C.c_double], C.c_void_p),
        ('cmsCreate_sRGBProfile', [], C.c_void_p),
        ('cmsCreateRGBProfile', [C.POINTER(XY), C.POINTER(Primaries), C.POINTER(C.c_void_p)], C.c_void_p),
        ('cmsSaveProfileToMem', [C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32)], C.c_int),
        ('cmsCloseProfile', [C.c_void_p], C.c_int),
        ('cmsFreeToneCurve', [C.c_void_p], None),
    ):
        fn = getattr(cms, name)
        fn.argtypes, fn.restype = args, result
    curve = cms.cmsBuildGamma(None, 1.)
    curves = (C.c_void_p * 3)(curve, curve, curve)
    white = XY(.3127, .3290, 1.)
    result = {'untagged': None, 'invalid': b'not an ICC profile'}
    for name, prim in [('srgb', None), ('linear-srgb', (.64, .33, .30, .60, .15, .06)),
                       ('linear-p3', (.68, .32, .265, .69, .15, .06))]:
        if prim:
            p = Primaries(*(XY(*prim[i:i+2], 1.) for i in (0, 2, 4)))
            profile = cms.cmsCreateRGBProfile(C.byref(white), C.byref(p), curves)
        else:
            profile = cms.cmsCreate_sRGBProfile()
        assert profile
        size = C.c_uint32()
        assert cms.cmsSaveProfileToMem(profile, None, C.byref(size))
        buf = C.create_string_buffer(size.value)
        assert cms.cmsSaveProfileToMem(profile, buf, C.byref(size))
        data = bytearray(buf.raw)
        data[24:36] = struct.pack('>6H', 2026, 1, 1, 0, 0, 0)
        result[name] = bytes(data)
        (root / (name + '.icc')).write_bytes(data)
        cms.cmsCloseProfile(profile)
    cms.cmsFreeToneCurve(curve)
    result['truncated'] = result['linear-srgb'][:100]
    return result


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))


def encode(samples, depth, channels, profile):
    raw = b''.join(struct.pack('>H' if depth == 16 else 'B', v) for p in samples for v in p[:channels])
    data = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', len(samples), 1, depth, 6 if channels == 4 else 2, 0, 0, 0))
    if profile is not None:
        data += chunk(b'iCCP', b'fixture\0\0' + zlib.compress(profile))
    return data + chunk(b'IDAT', zlib.compress(b'\0' + raw)) + chunk(b'IEND', b'')


def reference(samples, depth, channels, family):
    def transfer(v):
        v = max(0., min(1., v))
        return 12.92*v if v <= .0031308 else 1.055*v**(1/2.4)-.055
    output = []
    for sample in samples:
        rgb = [v / (2**depth-1) for v in sample[:3]]
        if family == 'linear-p3':
            # D65 Display-P3 to D65 sRGB, derived from declared xy primaries.
            r, g, b = rgb
            rgb = [1.224940176*r-.224940176*g, -.042056955*r+1.042056955*g,
                   -.019637555*r-.078636046*g+1.098273601*b]
        if family.startswith('linear'):
            rgb = [transfer(v) for v in rgb]
        alpha = sample[3]/(2**depth-1) if channels == 4 else 1.
        output.extend([math.floor(v*alpha*255+.5) for v in rgb] + [math.floor(alpha*255+.5)])
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build', type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    root = build / 'color'
    root.mkdir(exist_ok=True)
    destination = root / 'results.json'
    if destination.exists():
        shutil.copy2(destination, root / ('results-' + hashlib.sha256(destination.read_bytes()).hexdigest()[:12] + '.json'))
    reports = []
    profile_data = profiles(root)
    (root / 'manifest.json').write_text(json.dumps({
        'profiles': {k: hashlib.sha256(v).hexdigest() if v is not None else None for k,v in profile_data.items()},
        'binaries': {k: hashlib.sha256((build / k).read_bytes()).hexdigest() for k in
                     ('qt-worker', 'glycin-worker', 'rust/release/color-repro')},
        'policy': {'rgb_tolerance': 2, 'alpha_tolerance': 1, 'malformed': 'assumed sRGB; rejection unknown'},
    }, indent=2)+'\n')
    for family, profile in profile_data.items():
        if profile is not None:
            (root / (family + '.icc')).write_bytes(profile)
        for depth in (8, 16):
            for channels in (3, 4):
                maximum = 2**depth-1
                values = [(0,0,0), (1,1,1), (.02,.02,.02), (.18,.18,.18), (.5,.5,.5),
                          (1,0,0), (0,1,0), (0,0,1), (.8,.2,.05), (.1,.4,.7)]
                samples = [tuple(round(v*maximum) for v in rgb)+(round(a*maximum),)
                           for rgb in values for a in ((0,.25,.5,1) if channels == 4 else (1,))]
                expected = reference(samples, depth, channels, family)
                name = f'{family}-{depth}-{channels}'
                data = encode(samples, depth, channels, profile)
                (root / (name+'.png')).write_bytes(data)
                for backend in ('control', 'qt', 'glycin', 'raw-glycin'):
                    record = dict(fixture=name, backend=backend, fixture_profile=family,
                                  sha256=hashlib.sha256(data).hexdigest(), expected=expected,
                                  uncertainty='Malformed profile assumed sRGB; rejection distinction unknown' if family in ('invalid','truncated') else None)
                    worker = Worker(build / ('rust/release/color-repro' if backend == 'raw-glycin' else 'glycin-worker' if backend == 'glycin' else 'qt-worker'),
                                    isolated=backend != 'control', glycin='glycin' in backend)
                    try:
                        record['load'] = worker.request('load', data)
                        actual = worker.request('decode', width=len(samples), height=1, capture_pixels=True)
                        record['actual'] = actual
                        if actual.get('icc_hex') is not None:
                            raw_profile = bytes.fromhex(actual['icc_hex'])
                            record['client_icc_sha256'] = hashlib.sha256(raw_profile).hexdigest()
                            record['client_icc_matches_fixture'] = raw_profile == profile
                        pixels = actual.get('pixels', [])
                        differences = [a-b for a,b in zip(pixels, expected)]
                        record['differences'] = differences
                        record['passed'] = (actual['outcome'] in (0, 'success') and len(pixels) == len(expected)
                            and actual['width'] == len(samples) and actual['height'] == 1
                            and all(abs(d) <= (1 if i%4 == 3 else 2) for i,d in enumerate(differences))
                            and all(pixels[i:i+3] == [0,0,0] for i in range(0,len(pixels),4) if expected[i+3] == 0))
                    except (OSError, RuntimeError, ValueError, TimeoutError) as error:
                        record.update(passed=False, error=str(error))
                    finally:
                        record['stderr'] = worker.close()
                    reports.append(record)
    destination.write_text(json.dumps(reports, indent=2)+'\n')
    for backend in ('control', 'qt', 'glycin', 'raw-glycin'):
        rows = [r for r in reports if r['backend'] == backend]
        print(backend, sum(r['passed'] for r in rows), '/', len(rows), 'passed')
    return int(any(not r['passed'] for r in reports))


if __name__ == '__main__':
    raise SystemExit(main())
