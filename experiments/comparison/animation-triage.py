#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded GIF diagnosis, independent of acceptance and retention workloads."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import uuid
from animation import PALETTE, LOCAL, encode, reference, patch, fixtures
from harness import Worker


def validate(data, w, h, frames, repeat):
    """Parse fixture bytes without using the encoder's packing implementation."""
    pos = 0
    def take(n):
        nonlocal pos
        value = data[pos:pos+n]
        assert len(value) == n
        pos += n
        return value
    def blocks():
        result = b''
        while True:
            n = take(1)[0]
            if not n:
                return result
            result += take(n)
    assert take(6) == b'GIF89a'
    assert struct.unpack('<HHBBB', take(7)) == (w,h,129,0,0)
    assert take(12) == bytes(v for c in PALETTE for v in c)
    declaration = None
    count = 0
    while True:
        marker = take(1)
        if marker == b';':
            break
        assert marker == b'!'
        kind = take(1)
        if kind == b'\xff':
            assert take(1) == b'\x0b' and take(11) == b'NETSCAPE2.0'
            payload = blocks()
            assert len(payload) == 3 and payload[0] == 1
            declaration = int.from_bytes(payload[1:], 'little')
            continue
        assert kind == b'\xf9' and take(1) == b'\x04'
        flags, delay, transparent = struct.unpack('<BHB', take(4))
        assert take(1) == b'\0' and take(1) == b','
        x,y,fw,fh,packed = struct.unpack('<HHHHB', take(9))
        f = frames[count]
        assert 0 <= x < w and 0 <= y < h and 0 < fw <= w-x and 0 < fh <= h-y
        assert (x,y,fw,fh) == tuple(f[k] for k in ('x','y','w','h'))
        assert flags == f['disposal']*4 + (f['transparent'] is not None)
        assert delay == (3,7,11)[count%3] and transparent == (f['transparent'] or 0)
        assert packed == (129 if f['local'] else 0)
        if packed:
            assert take(12) == bytes(v for c in LOCAL for v in c)
        assert take(1) == b'\x02'
        compressed = blocks()
        bits = ''.join(f'{b:08b}'[::-1] for b in compressed)
        codes = [int(bits[i:i+3][::-1],2) for i in range(0,len(bits)-2,3)]
        end = 2*fw*fh
        assert codes[end] == 5 and all(c == 4 for c in codes[:end:2])
        assert codes[1:end:2] == f['indices']
        assert set(bits[(end+1)*3:]) <= {'0'}
        count += 1
    assert pos == len(data) and count == len(frames) and declaration == repeat


def self_checks():
    def solid(x, color, disposal=1, transparent=None):
        return dict(patch(x,0,1,1,disposal,transparent), indices=[color])
    base = dict(patch(0,0,2,1), indices=[1,2])
    rgba = lambda a,b: bytes((*PALETTE[a],255,*PALETTE[b],255))
    for disposal, expected in ((1,rgba(3,1)),(2,rgba(0,1)),(3,rgba(1,1))):
        assert list(reference(2,1,[base,solid(0,3,disposal),solid(1,1)]))[-1] == expected
    assert list(reference(2,1,[base,solid(0,0,transparent=0)]))[-1] == rgba(1,2)
    assert list(reference(2,1,[base,solid(0,3,3),solid(1,3,3),solid(0,2)]))[-1] == rgba(2,2)
    assert list(reference(2,1,[base,dict(solid(0,3),local=True)]))[-1] == bytes((*LOCAL[3],255,*PALETTE[2],255))
    for name, fs in fixtures().items():
        for repeat in (None,0,2):
            validate(encode(12,8,fs,repeat),12,8,fs,repeat)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build',type=Path)
    parser.add_argument('--self-check',action='store_true')
    args = parser.parse_args()
    build = args.build.resolve()
    root = build / ('animation-triage-'+time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    self_checks()
    (root/'oracle.json').write_text(json.dumps(dict(status='passed',checks='parsed fixture bytes and hand-calculated canvases')))
    if args.self_check:
        print(root)
        return 0
    results = []
    def save():
        (root/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    def run(binary, name, w,h,fs,repeat=None,exhaust=False):
        directory = root / f'{len(results):04d}-{name}-{binary}'
        directory.mkdir()
        data = encode(w,h,fs,repeat)
        validate(data,w,h,fs,repeat)
        (directory/'fixture.gif').write_bytes(data)
        (directory/'definition.json').write_text(json.dumps(dict(width=w,height=h,frames=fs,repeat=repeat)))
        expected = list(reference(w,h,fs))
        record = dict(binary=binary,name=name,status='passed',requests=[],frames=[],directory=directory.name)
        results.append(record)
        worker = None
        def request(op, **kw):
            response = worker.request(op, **kw)
            pixels = bytes(response.pop('pixels',[]))
            record['requests'].append(dict(op=op,fields={k:v for k,v in kw.items() if k!='payload'},response=response))
            return response,pixels
        try:
            worker = Worker(build/binary,runtime_bundle=build/'runtime-bundle',glycin='glycin' in binary)
            def load(op):
                r,_ = request(op,**({'payload':data} if op=='load' else {}))
                assert r['outcome'] == ('success' if binary == 'qt-worker' and op == 'restart' else 'loaded'),r
                if binary == 'qt-worker':
                    r,_ = request('gif-open')
                    assert r['outcome'] == 'success',r
            load('load')
            for cycle in range(3 if exhaust else 1):
                if cycle:
                    load('restart')
                count = 1 if cycle == 1 else len(fs)
                for i in range(count+(4 if exhaust and cycle!=1 else 0)):
                    r,pixels = request('frame',width=w,height=h,capture_pixels=True)
                    label = f'{cycle}-{i}'
                    (directory/(label+'-actual.rgba')).write_bytes(pixels)
                    if i<len(fs):
                        want = expected[i]
                        (directory/(label+'-expected.rgba')).write_bytes(want)
                        (directory/(label+'-difference.rgba')).write_bytes(bytes(abs(a-b) for a,b in zip(want,pixels)))
                        diff = next((j for j,(a,b) in enumerate(zip(want,pixels)) if a!=b),None)
                        mismatch = pixels != want or (r.get('width'),r.get('height')) != (w,h)
                        delay = r.get('delay_ms', (r.get('delay_us') or 0)/1000)
                        record['frames'].append(dict(cycle=cycle,index=i,pixel_mismatch=mismatch,
                            first_difference=None if diff is None else dict(x=(diff//4)%w,y=diff//4//w,channel=diff%4,expected=want[diff],actual=pixels[diff]),
                            delay_mismatch=delay!=(30,70,110)[i%3]))
                        if mismatch or delay!=(30,70,110)[i%3]: record['status']='failed'
                        if r['outcome']!='success': record['status']='unproven'
                    elif r['outcome']!='end':
                        record['status']='failed' if r['outcome']=='success' else 'unproven'
        except (OSError,RuntimeError,ValueError,TimeoutError,AssertionError) as error:
            record.update(status='unproven',error=str(error))
        finally:
            if worker:
                record['stderr']=worker.close()
                record['scope_empty']=worker.scope_empty
                record['memory_series']=worker.memory_series
                if not worker.scope_empty: record['status']='unproven'
            save()
        print(name,binary,record['status'],flush=True)
        return record
    def final_mismatch(r,n):
        return r['status']!='unproven' and any(f['index']==n-1 and f['pixel_mismatch'] for f in r['frames'])
    retention = [patch(0,0,256,128)] + [patch(0,0,256,128,seed=i) if i%8==0 else
        patch((i*13)%192,(i*7)%96,64,32,1+i%3,0 if i%4==0 and i%3!=1 else None,i%5==0,i) for i in range(1,12)]
    seeds = [('qt-prefix',256,128,retention,'qt'),('glycin-prefix',256,128,retention[:3],'glycin'),
             ('glycin-disposal-2',12,8,fixtures()['disposal-2'],'glycin')]
    reductions=[]
    comparisons=[]
    def compare(name,w,h,fs,backend,repeat=None,exhaust=False):
        for trial in range(3):
            raw=run(backend+'-animation-repro',name+f'-confirm-{trial}',w,h,fs,repeat,exhaust)
            wrapped=run(backend+'-worker',name+f'-confirm-{trial}',w,h,fs,repeat,exhaust)
            def signature(r):
                return [(q['response'].get('outcome'),q['response'].get('width',0),q['response'].get('height',0),
                    (q['response'].get('delay_ms',(q['response'].get('delay_us') or 0)/1000) if q['response'].get('outcome')=='success' else None),q['response'].get('pixel_sha256'))
                    for q in r['requests'] if q['op']=='frame']
            comparisons.append(dict(name=name,trial=trial,status='unproven' if 'unproven' in (raw['status'],wrapped['status'])
                else 'passed' if signature(raw)==signature(wrapped) else 'failed',raw=raw['directory'],wrapper=wrapped['directory']))
    for name,w,h,fs,backend in seeds:
        initial=run(backend+'-animation-repro',name,w,h,fs)
        history=[]
        current=list(fs)
        trials=0
        if final_mismatch(initial,len(fs)):
            while trials<32:
                improved=False
                for i in range(1,len(current)-1):
                    if trials>=32: break
                    candidate=current[:i]+current[i+1:]
                    r=run(backend+'-animation-repro',name+f'-reduce-{trials}',w,h,candidate)
                    accepted=final_mismatch(r,len(candidate))
                    history.append(dict(removed=i,accepted=accepted,evidence=r['directory']))
                    trials+=1
                    if accepted:
                        current=candidate
                        improved=True
                        break
                if not improved: break
        reductions.append(dict(name=name,frames=current,history=history,claim='smallest found by bounded greedy removal; global minimality unproven'))
        compare(name+'-final',w,h,current,backend)
    base=dict(patch(0,0,3,2),indices=[1]*6)
    overlay=dict(patch(0,0,1,1),indices=[2])
    tail=dict(patch(2,1,1,1),indices=[3])
    controls={'opaque':[base,overlay,tail], 'local':[base,dict(overlay,local=True),tail],
        'disposal-2':[base,dict(overlay,disposal=2),tail],
        'disposal-2-local':[base,dict(overlay,disposal=2,local=True),tail],
        'transparent':[base,dict(overlay,transparent=2),tail],
        'disposal-3':[base,dict(overlay,disposal=3),tail],
        'consecutive-3':[base,dict(overlay,disposal=3),dict(tail,disposal=3),overlay]}
    for name,fs in controls.items():
        for backend in ('qt','glycin'): compare('control-'+name,3,2,fs,backend)
    full=[dict(patch(0,0,2,2),indices=[i]*4) for i in (1,2)]
    for repeat in (None,2,0):
        for backend in ('qt','glycin'): compare('exhaustion-'+str(repeat),2,2,full,backend,repeat,True)
    (root/'reductions.json').write_text(json.dumps(reductions,indent=2))
    (root/'wrapper-equivalence.json').write_text(json.dumps(comparisons,indent=2))
    identities={}
    for command in (['git','rev-parse','HEAD'],['pacman','-Q','qt6-base','qt6-imageformats','glycin'],['rustc','--version']):
        r=subprocess.run(command,capture_output=True,text=True)
        identities[' '.join(command)]=dict(returncode=r.returncode,stdout=r.stdout,stderr=r.stderr)
    identities['binaries']={n:hashlib.sha256((build/n).read_bytes()).hexdigest() for n in
        ('qt-worker','glycin-worker','qt-animation-repro','glycin-animation-repro')}
    identities['sources']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.rglob('*')
        if p.is_file() and p.suffix in ('.py','.cpp','.rs','.toml','.lock','.txt')}
    (root/'identities.json').write_text(json.dumps(identities,indent=2))
    (root/'manifest.json').write_text(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob('*') if p.is_file()},indent=2))
    print(root)
    return int(any(r['status']!='passed' for r in results+comparisons))


if __name__=='__main__':
    raise SystemExit(main())
