#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent GIF89a compositing and bounded post-warmup session retention."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import struct
import time
import uuid
from harness import Worker

PALETTE = [(19, 37, 61), (221, 43, 79), (47, 193, 101), (71, 89, 233)]
LOCAL = [(239, 181, 23), (31, 211, 199), (173, 59, 211), (251, 239, 223)]
LIMIT = 32 * 1024**2


def patch(x, y, w, h, disposal=1, transparent=None, local=False, seed=0):
    return dict(x=x, y=y, w=w, h=h, disposal=disposal, transparent=transparent,
                local=local, indices=[(i + i // w + seed) % 4 for i in range(w*h)])


def encode(w, h, frames, repeat=None):
    """Clear before every literal keeps all LZW codes three bits wide."""
    data = b'GIF89a' + struct.pack('<HHBBB', w, h, 0x81, 0, 0)
    data += bytes(v for color in PALETTE for v in color)
    if repeat is not None:
        data += b'\x21\xff\x0bNETSCAPE2.0\x03\x01' + struct.pack('<H', repeat) + b'\0'
    for n, f in enumerate(frames):
        packed = f['disposal'] << 2 | (f['transparent'] is not None)
        data += b'\x21\xf9\x04' + struct.pack('<BHB', packed, (3,7,11)[n%3], f['transparent'] or 0) + b'\0'
        data += b'\x2c' + struct.pack('<HHHHB', f['x'], f['y'], f['w'], f['h'], 0x81 if f['local'] else 0)
        if f['local']:
            data += bytes(v for color in LOCAL for v in color)
        codes = [code for index in f['indices'] for code in (4, index)] + [5]
        # Minimum code size 2: repeated clear/literal pairs never grow beyond 3 bits.
        bits = bytearray((len(codes)*3+7)//8)
        for i, code in enumerate(codes):
            for bit in range(3):
                bits[(i*3+bit)//8] |= ((code >> bit)&1) << ((i*3+bit)%8)
        data += b'\x02' + b''.join(bytes([len(bits[i:i+255])])+bits[i:i+255] for i in range(0,len(bits),255)) + b'\0'
    return data + b'\x3b'


def reference(w, h, frames):
    """Dispose previous rectangle before drawing; snapshot only the affected area."""
    canvas = [PALETTE[0]] * (w*h)
    previous = None
    saved = None
    for f in frames:
        if previous:
            positions = [(previous['y']+y)*w+previous['x']+x
                         for y in range(previous['h']) for x in range(previous['w'])]
            if previous['disposal'] == 2:
                for pos in positions:
                    canvas[pos] = PALETTE[0]
            elif previous['disposal'] == 3:
                for pos, color in zip(positions, saved):
                    canvas[pos] = color
        positions = [(f['y']+y)*w+f['x']+x for y in range(f['h']) for x in range(f['w'])]
        saved = [canvas[pos] for pos in positions] if f['disposal'] == 3 else None
        palette = LOCAL if f['local'] else PALETTE
        for pos, index in zip(positions, f['indices']):
            if index != f['transparent']:
                canvas[pos] = palette[index]
        yield bytes(v for color in canvas for v in (*color,255))
        previous = f


def fixtures():
    base = patch(0,0,12,8)
    one = [patch(2,1,7,4,seed=1), patch(5,3,6,4,seed=2)]
    two = [patch(1,2,8,5,2), patch(6,1,5,5)]
    three = [patch(2,1,7,5,3), patch(4,2,6,4,3,seed=2), patch(1,3,8,4)]
    transparent = [patch(3,2,8,5,transparent=0)]
    local = [patch(1,1,9,6,local=True), patch(4,3,7,4)]
    return {name:[base]+seq for name,seq in [('disposal-1',one),('disposal-2',two),
            ('disposal-3',three),('transparent',transparent),('local-palette',local),
            ('mixed',one+two+three+transparent+local)]}


def analyze(points, expected):
    if len(points) != expected or any(p is None or any(k not in p for k in
            ('rss_bytes','anonymous_bytes','memory_current_bytes','process_count','timestamp')) for p in points):
        return dict(status='unproven', reason='missing checkpoints')
    growth = {k:statistics.median(p[k] for p in points[-8:]) -
              statistics.median(p[k] for p in points[:8]) for k in ('rss_bytes','anonymous_bytes')}
    return dict(status='passed' if all(v <= LIMIT for v in growth.values()) else 'failed',
                growth_bytes=growth, first_medians={k:statistics.median(p[k] for p in points[:8]) for k in growth},
                last_medians={k:statistics.median(p[k] for p in points[-8:]) for k in growth})


def analysis_checks():
    points = [dict(rss_bytes=100, anonymous_bytes=100, memory_current_bytes=200,
                   process_count=1, timestamp=i) for i in range(64)]
    assert analyze(points,64)['status'] == 'passed'
    assert analyze(points[:-1],64)['status'] == 'unproven'
    assert analyze(points[:-1]+[None],64)['status'] == 'unproven'
    for key in ('rss_bytes','anonymous_bytes'):
        trace = [dict(p, **{key:p[key]+(LIMIT+1 if i>=56 else 0)}) for i,p in enumerate(points)]
        assert analyze(trace,64)['status'] == 'failed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build',type=Path)
    parser.add_argument('--skip-retention', action='store_true', help='Run existing compositing/restart checks only')
    args = parser.parse_args()
    build = args.build.resolve()
    root = build / ('animation-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
    root.mkdir()
    analysis_checks()
    results = []

    def execute(backend, name, action):
        worker = Worker(build / ('glycin-worker' if backend=='glycin' else 'qt-worker'),
                        isolated=backend!='direct', glycin=backend=='glycin')
        record = dict(backend=backend, name=name, responses=[], checkpoints=[])
        try:
            action(worker, record)
            record.setdefault('status','passed')
            if record.get('frame_failures'):
                record['status'] = 'failed'
        except (AssertionError, OSError, RuntimeError, ValueError, TimeoutError) as error:
            record.update(status='unproven' if not isinstance(error,AssertionError) else 'failed', error=str(error))
        finally:
            if name in ('traversal','partial') and 'retention_analysis' not in record:
                record['retention_analysis'] = dict(status='unproven',reason='incomplete workload')
            record['stderr'] = worker.close()
            record['scope_empty'] = worker.scope_empty
            record['memory_series'] = worker.memory_series
            record['peak_rss_kib'] = worker.peak_rss_kib
            if not worker.scope_empty:
                record['closure_error'] = 'scope closure not verified'
                record['status'] = 'unproven'
            results.append(record)
            (root/'results.json').write_text(json.dumps(results,indent=2)+'\n')
        print(backend,name,record['status'],record.get('error',''),flush=True)

    def request(worker, record, op, **kw):
        r = worker.request(op, **kw)
        pixels = bytes(r.pop('pixels', []))
        record['responses'].append(r)
        return r,pixels

    def load(worker, record, data):
        r,_ = request(worker,record,'load',payload=data)
        fact = r['intrinsic_loop']
        if record['backend'] != 'glycin':
            request(worker,record,'gif-open')
        return fact

    def frame(worker, record, expected, w, h, index, label=None):
        r,pixels = request(worker,record,'frame',width=w,height=h,capture_pixels=True)
        if label:
            (root/(label+'-actual.rgba')).write_bytes(pixels)
            (root/(label+'-difference.rgba')).write_bytes(bytes(abs(a-b) for a,b in zip(expected,pixels)))
        assert (r.get('width'),r.get('height')) == (w,h), r
        if pixels != expected:
            record.setdefault('frame_failures', []).append(dict(index=index, reason='pixels', label=label))
        if r.get('delay_ms',r.get('delay_us',0)/1000) != (30,70,110)[index%3]:
            record.setdefault('frame_failures', []).append(dict(index=index,reason='delay',label=label))

    for backend in ('direct','qt','glycin'):
        for name,frames in fixtures().items():
            for repeat in ((None,2,0) if name=='mixed' else (None,)):
                label = f'{backend}-{name}-{repeat}'
                data = encode(12,8,frames,repeat)
                (root/(label+'.gif')).write_bytes(data)
                expected = list(reference(12,8,frames))
                for i,pixels in enumerate(expected):
                    (root/f'{label}-{i}-expected.rgba').write_bytes(pixels)
                def compositing(worker, record):
                    fact = load(worker,record,data)
                    assert fact == dict(provenance='supplemental-gif-block-reader',scan_status='complete',
                        raw_declaration=repeat,total_plays=None if repeat==0 else 1 if repeat is None else repeat+1,infinite=repeat==0), fact
                    inspection,_ = request(worker,record,'inspect')
                    for key,value in dict(source_width=12,source_height=8,oriented_width=12,oriented_height=8,orientation=1,orientation_policy='Apply').items():
                        assert inspection.get(key)==value, (key,inspection)
                    if backend != 'glycin':
                        request(worker,record,'gif-open')
                    for cycle in range(4):
                        if cycle:
                            r,_ = request(worker,record,'restart')
                            assert r['intrinsic_loop'] == fact
                            again,_ = request(worker,record,'inspect')
                            assert again == inspection, (again,inspection)
                            if backend != 'glycin':
                                request(worker,record,'gif-open')
                        for i,pixels in enumerate(expected):
                            frame(worker,record,pixels,12,8,i,f'{label}-{cycle}-{i}')
                            if cycle==2 and i==len(expected)//2:
                                break
                        if cycle!=2:
                            for _ in range(4):
                                r,_ = request(worker,record,'frame')
                                if r['outcome']!='end':
                                    record.setdefault('frame_failures', []).append(dict(reason='exhaustion',cycle=cycle))
                execute(backend,label,compositing)

    frames = [patch(0,0,256,128)] + [patch(0,0,256,128,seed=i) if i%8==0 else
              patch((i*13)%192,(i*7)%96,64,32,1+i%3,0 if i%4==0 and i%3!=1 else None,i%5==0,i) for i in range(1,128)]
    data = encode(256,128,frames)
    (root/'retention.gif').write_bytes(data)
    (root/'retention-definition.json').write_text(json.dumps(frames))
    hashes = [hashlib.sha256(p).hexdigest() for p in reference(256,128,frames)]
    (root/'retention-expected-hashes.json').write_text(json.dumps(hashes))
    for backend in (() if args.skip_retention else ('direct','qt','glycin')):
        deadline = time.monotonic()+180
        for workload in ('traversal','partial'):
            def retention(worker, record):
                worker.operation_deadline = deadline
                load(worker,record,data)
                warmup,cycles,count = (1,9,128) if workload=='traversal' else (4,68,4)
                for cycle in range(cycles):
                    if time.monotonic()>=deadline:
                        raise TimeoutError('180 second combined workload cap')
                    request(worker,record,'restart')
                    for i in range(count):
                        if time.monotonic()>=deadline:
                            raise TimeoutError('180 second combined workload cap')
                        r,pixels = request(worker,record,'frame',width=256,height=128,capture_pixels=True)
                        assert (r.get('width'),r.get('height')) == (256,128), r
                        if hashlib.sha256(pixels).hexdigest()!=hashes[i]:
                            record.setdefault('frame_failures', []).append(dict(cycle=cycle,index=i,reason='pixels'))
                        if r.get('delay_ms',r.get('delay_us',0)/1000)!=(30,70,110)[i%3]:
                            record.setdefault('frame_failures', []).append(dict(cycle=cycle,index=i,reason='delay'))
                        if cycle>=warmup and ((i+1)%16==0 if workload=='traversal' else i==3):
                            record['checkpoints'].append(worker.sample())
                    if workload=='traversal':
                        r,_ = request(worker,record,'frame')
                        assert r['outcome']=='end', r
                record['retention_analysis'] = analyze(record['checkpoints'],64)
                record['status'] = record['retention_analysis']['status']
            execute(backend,workload,retention)
    manifest = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    (root/'manifest.json').write_text(json.dumps(dict(files=manifest,binaries={p:hashlib.sha256((build/p).read_bytes()).hexdigest() for p in ('qt-worker','glycin-worker')}),indent=2))
    print(root)
    return any(r['status']!='passed' for r in results)


if __name__ == '__main__':
    raise SystemExit(main())
