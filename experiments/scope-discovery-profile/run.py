#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""One bounded private run. Never installs, retries, or executes frozen payloads."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import struct
import subprocess
import tarfile
import tempfile
import time
import zlib

import accounting as a
import overlay

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UMBRELLA = ROOT.parent
FIXTURE_HASH = '610672660f509f2fc6afff14459f7c5575c5f3589c0354938d02376f9874e587'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def inventory(root):
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('symlink in private inventory')
        if p.is_file():
            result[str(p.relative_to(root))] = dict(sha256=sha(p), size=p.stat().st_size, mode=p.stat().st_mode & 0o7777)
        elif not p.is_dir():
            raise ValueError('nonregular private inventory')
    return result


def stage_tooling(snapshot, destination):
    expected = inventory(snapshot)
    # Overlay tracked files, but never silently retain stale archive contents.
    inventory(destination)
    shutil.copytree(snapshot, destination, dirs_exist_ok=True)
    if inventory(destination) != expected:
        raise ValueError('staged tooling inventory mismatch (including stale extra files)')


def fixture(source, destination):
    if sha(source) != FIXTURE_HASH:
        raise ValueError('preserved fixture hash mismatch')
    data = source.read_bytes()
    chunks, pos = {}, 8
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('PNG signature')
    while pos < len(data):
        n = struct.unpack('>I', data[pos:pos+4])[0]
        tag, payload = data[pos+4:pos+8], data[pos+8:pos+8+n]
        if zlib.crc32(tag+payload) != struct.unpack('>I', data[pos+8+n:pos+12+n])[0]:
            raise ValueError('PNG CRC')
        chunks.setdefault(tag, []).append(payload)
        pos += 12+n
    if struct.unpack('>IIBBBBB', chunks[b'IHDR'][0]) != (160,80,8,2,0,0,0):
        raise ValueError('unexpected fixture facts')
    encoded = zlib.decompress(b''.join(chunks[b'IDAT']))
    if len(encoded) != 80*481:
        raise ValueError('PNG scanline length')
    previous = bytes(480)
    rgb = bytearray()
    for y in range(80):
        method, row = encoded[y*481], bytearray(encoded[y*481+1:(y+1)*481])
        for x in range(480):
            left, up, corner = row[x-3] if x>=3 else 0, previous[x], previous[x-3] if x>=3 else 0
            p = left+up-corner
            distances = [abs(p-left), abs(p-up), abs(p-corner)]
            paeth = (left,up,corner)[distances.index(min(distances))]
            if method > 4:
                raise ValueError('PNG filter')
            row[x] = (row[x] + (0,left,up,(left+up)//2,paeth)[method]) & 255
        rgb.extend(row)
        previous = row
    rgba = b''.join(rgb[i:i+3]+b'\xff' for i in range(0,len(rgb),3))
    destination.mkdir()
    shutil.copyfile(source, destination/'source.png')
    def chunk(tag, payload):
        return struct.pack('>I',len(payload))+tag+payload+struct.pack('>I',zlib.crc32(tag+payload))
    cached = b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',chunks[b'IHDR'][0])+chunk(b'IDAT',zlib.compress(b''.join(b'\0'+rgb[y*480:(y+1)*480] for y in range(80))))+chunk(b'IEND',b'')
    (destination/'cached.png').write_bytes(cached)
    return dict(source_sha256=sha(destination/'source.png'), cached_sha256=sha(destination/'cached.png'),
                pixels_sha256=hashlib.sha256(rgba).hexdigest(), width=160,height=80,
                pixel_colors=sorted({tuple(rgba[i:i+4]) for i in range(0,len(rgba),4)}),
                inspection=dict(format='png', source_width=160,source_height=80,oriented_width=160,oriented_height=80,orientation=0,metadata_empty=True,outcome=0))


class Run:
    def __init__(self, output):
        self.output = output
        self.commands = []

    def command(self, args, cwd=None, timeout=180):
        args = [str(v) for v in args]
        index = len(self.commands)
        row = dict(args=args,cwd=str(cwd or ROOT),timeout=timeout)
        self.commands.append(row)
        save(self.output/'commands.json',self.commands)
        with (self.output/f'command-{index:03}.log').open('wb') as log:
            result = subprocess.run(args,cwd=cwd or ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
        row['exit'] = result.returncode
        row['log_sha256'] = sha(self.output/f'command-{index:03}.log')
        save(self.output/'commands.json',self.commands)
        if result.returncode:
            raise ValueError(f'command failed: {args}; log command-{index:03}.log')
        return (self.output/f'command-{index:03}.log').read_text()

    def build(self):
        commit = self.command(['git','rev-parse','HEAD']).strip()
        tree = self.command(['git','rev-parse','HEAD^{tree}']).strip()
        archive = self.output/'images.tar'
        shutil.copyfile(ROOT/'build/scope-discovery-feasibility-20261109/images.tar', archive)
        provenance = dict(commit=commit,tree=tree,archive_sha256=sha(archive),variants={})
        save(self.output/'provenance.json',provenance)
        shutil.copytree(HERE,self.output/'tooling',ignore=shutil.ignore_patterns('__pycache__'))
        save(self.output/'tooling-inventory.json',inventory(self.output/'tooling'))
        self.command(['c++','--version'])
        self.command(['clang-format','--version'])
        self.command(['cmake','--version'])
        self.command(['pkg-config','--modversion','Qt6Core','Qt6Gui','libexif','libwebp'])
        self.command(['uname','-a'])
        provenance['environment'] = {k:os.environ.get(k) for k in ('PATH','LANG','LC_ALL','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','LD_LIBRARY_PATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM')}
        provenance['launcher_tools'] = {p:sha(Path(p)) for p in ('/usr/bin/bwrap','/usr/bin/systemd-run','/usr/bin/systemctl')}
        plugins = self.command(['/usr/lib/qt6/bin/qtpaths6','--query','QT_INSTALL_PLUGINS']).strip()
        builds = {}
        for variant in a.VARIANTS:
            home = self.output/variant
            source, build = home/'source', home/'build'
            source.mkdir(parents=True)
            with tarfile.open(archive) as tar:
                tar.extractall(source,filter='data')
            experiment = source/'experiments/scope-discovery-profile'
            stage_tooling(self.output/'tooling',experiment)
            patch = home/'overlay.patch'
            patch.write_text(overlay.apply(source,variant=='observed'))
            save(home/'source-inventory.json',inventory(source))
            # Reviewable exact anchors leave all security/lifecycle checks in place.
            self.command(['cmake','-S',experiment,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
                          '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'])
            self.command(['cmake','--build',build,'--target','scope-discovery-profile','holonight-images-helper','-j','4'])
            self.command(['ninja','-C',build,'-t','commands'])
            helper = build/'images/holonight-images-helper'
            binary = build/'scope-discovery-profile'
            self.command(['ldd',helper]); self.command(['ldd',binary])
            bundle = home/'runtime'
            self.command(['python3',source/'scripts/prepare-isolated-runtime.py','--helper',helper,'--plugins',plugins,'--output',bundle])
            inv = inventory(bundle)
            save(home/'runtime-inventory.json',inv)
            provenance['variants'][variant] = dict(binary_sha256=sha(binary),helper_sha256=sha(helper),overlay_sha256=sha(patch),
                source_inventory_sha256=sha(home/'source-inventory.json'),runtime_inventory_sha256=sha(home/'runtime-inventory.json'))
            builds[variant] = dict(binary=binary,bundle=bundle,inventory=inv)
            save(self.output/'provenance.json',provenance)
        return builds


def emergency(process, journal):
    """One shared five-second deadline: manager kill, harness reaping, tree proof."""
    deadline = time.monotonic()+5
    evidence = dict(verified=False, commands=[], unit=None, group=None)
    def command(args):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('emergency budget')
        p = subprocess.run(['/usr/bin/systemctl','--user']+args,capture_output=True,timeout=remaining)
        evidence['commands'].append(dict(args=args,exit=p.returncode,stdout=p.stdout[:4096].decode(errors='replace'),stderr=p.stderr[:4096].decode(errors='replace')))
        return p
    try:
        unit = journal.read_text().strip() if journal.exists() else ''
        evidence['unit'] = unit
        if unit and not __import__('re').fullmatch(r'holonight-images-[a-f0-9]{32}\.scope',unit):
            raise ValueError('invalid unit journal')
        group = None
        if unit:
            query = command(['show','--property=ControlGroup','--value',unit])
            path = query.stdout.decode().strip()
            if query.returncode==0 and path.startswith('/') and path.endswith('/'+unit) and '..' not in path.split('/'):
                group = Path('/sys/fs/cgroup'+path)
                evidence['group'] = str(group)
            command(['kill','--signal=KILL',unit])
        try:
            os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=max(.001,deadline-time.monotonic()))
        while time.monotonic()<deadline:
            if group:
                try:
                    lines = (group/'cgroup.events').read_text().splitlines()
                    if lines.count('populated 0')==1 and not any(s.startswith('populated ') and s!='populated 0' for s in lines):
                        evidence.update(verified=True,proof='populated-zero'); break
                except FileNotFoundError:
                    if not group.exists():
                        evidence.update(verified=True,proof='removed'); break
            elif unit:
                state = command(['show','--property=LoadState','--value',unit])
                if state.returncode==0 and state.stdout.strip()==b'not-found':
                    evidence.update(verified=True,proof='manager-not-found'); break
            else:
                # Harness writes unit before launcher start; absent journal proves no dispatch.
                evidence.update(verified=True,proof='no-launch-journal'); break
            time.sleep(min(.005,max(0,deadline-time.monotonic())))
    except Exception as exc:
        evidence['error'] = str(exc)
    return evidence


def call(binary, bundle, fixture_path, slot, directory):
    directory.mkdir()
    journal, result = directory/'unit', directory/'result.json'
    command = [str(binary),str(bundle),str(fixture_path),slot['kind'],slot['case'],str(journal),str(result)]
    save(directory/'dispatch.json',dict(slot=slot,command=command,clock='CLOCK_MONOTONIC',dispatch_ns=time.monotonic_ns()))
    started = time.monotonic()
    p = subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    selector = selectors.DefaultSelector()
    for stream in (p.stdout,p.stderr):
        os.set_blocking(stream.fileno(),False)
        selector.register(stream,selectors.EVENT_READ)
    captured = {p.stdout:bytearray(),p.stderr:bytearray()}
    failure = None
    try:
        while selector.get_map() or p.poll() is None:
            remaining = 25-(time.monotonic()-started)
            if remaining<=0:
                raise TimeoutError('25 second call watchdog')
            for key,_ in selector.select(min(.02,remaining)):
                data = os.read(key.fd,4096)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    retained = captured[key.fileobj]
                    room = a.BYTE_LIMIT-len(retained)
                    retained.extend(data[:room])
                    if len(data)>room:
                        raise ValueError('harness stream cap')
        p.wait(timeout=max(.001,25-(time.monotonic()-started)))
    except Exception as exc:
        failure = str(exc)
        save(directory/'watchdog.json',dict(reason=failure,cleanup=emergency(p,journal)))
    finally:
        selector.close()
        for stream,name in ((p.stdout,'stdout'),(p.stderr,'stderr')):
            (directory/(name+'.raw')).write_bytes(captured[stream])
            stream.close()
    if failure:
        raise ValueError(failure)
    if p.returncode or not result.exists() or result.stat().st_size > 8*1024*1024:
        raise ValueError('harness failed/missing/oversized result')
    return json.loads(result.read_text())


def validate(slot, result, expected, directory):
    raw = base64.b64decode(result['stderr_base64'],validate=True)
    (directory/'launcher-stderr.raw').write_bytes(raw)
    events = result['events'] + a.parse(raw)
    save(directory/'events.json',[dict(e,operation=slot['id'],phase=slot['phase'],order=slot['order'],variant=slot['variant'],kind=slot['kind'],block=slot['block'],pair=slot['pair'],warmup=slot['warmup']) for e in events])
    if result.get('version') != 1 or result['unknown'] or result['capture_failed'] or len(result['events'])>a.LIMIT:
        raise ValueError('capture failed')
    a.validate_sequences(result['events'])
    if slot['case'] in ('measure','success') and raw:
        raise ValueError('normal child telemetry must be disabled')
    cleanup = result['cleanup'].get('cleanup',{})
    if not cleanup.get('verified') or cleanup.get('launcher_state')!=0 or cleanup.get('elapsed_ms',5001)>5000 or cleanup.get('proof') not in ('removed','populated-zero','manager-not-found'):
        raise ValueError('cleanup/reaping proof failed')
    case = slot['case']
    wanted = {'measure':0,'success':0,'before':5,'await':5,'timeout':3,'failed':1,'descendant':5}[case]
    if result['status']!=wanted or result['present']!=(wanted==0):
        raise ValueError(f'unexpected status/publication: {result["status"]}, wanted {wanted}')
    if wanted==0:
        for key,value in expected['inspection'].items():
            if result.get(key)!=value:
                raise ValueError('incorrect inspection: '+key)
        if slot['kind']!='inspection' and (result.get('pixels_sha256')!=expected['pixels_sha256'] or result.get('width')!=160 or result.get('height')!=80 or result.get('decode_outcome')!=0):
            raise ValueError('incorrect decoded pixels')
        return a.intervals(result['events'],slot['variant']=='observed',result['queries'],result['waits'],result['unknown'])
    marks = {e['mark'] for e in events}
    if case=='before' and ('L' not in marks or 'H' in marks):
        raise ValueError('before-release fault location')
    if case in ('await','timeout','failed','descendant') and ('H' not in marks or 'P2' in marks):
        raise ValueError('await-readiness fault location')
    if case=='descendant' and ('descendant' not in marks or not any('--signal=KILL' in c['arguments'] for c in cleanup['commands'])):
        raise ValueError('TERM-resistant descendant was not killed hierarchically')
    return a.intervals(result['events'],slot['variant']=='observed',result['queries'],result['waits'],result['unknown'],readiness=False)


def integrity(output):
    for name, path in [('tooling',output/'tooling'),('fixture',output/'fixtures')]:
        if inventory(path)!=json.loads((output/(name+'-inventory.json')).read_text()):
            raise ValueError(name+' mutation')
    provenance = json.loads((output/'provenance.json').read_text())
    if sha(output/'images.tar') != provenance['archive_sha256']:
        raise ValueError('archive mutation')
    for variant in a.VARIANTS:
        home = output/variant
        for name in ('source','runtime'):
            if inventory(home/name)!=json.loads((home/(name+'-inventory.json')).read_text()):
                raise ValueError(variant+' '+name+' mutation')
        expected = provenance['variants'][variant]
        for key,path in [('binary_sha256',home/'build/scope-discovery-profile'),
                         ('helper_sha256',home/'build/images/holonight-images-helper'),
                         ('overlay_sha256',home/'overlay.patch')]:
            if sha(path)!=expected[key]:
                raise ValueError(variant+' '+key+' mutation')
    for path,digest in provenance['launcher_tools'].items():
        if sha(Path(path)) != digest:
            raise ValueError('launcher tool mutation: '+path)
    frozen = json.loads((output/'frozen.json').read_text())
    for name, digest in frozen.items():
        if sha(output/name)!=digest:
            raise ValueError('frozen evidence mutation: '+name)


def prepare(fixture_path):
    output = Path(tempfile.mkdtemp(prefix='scope-discovery-',dir=ROOT/'build'))
    print(output,flush=True)
    audit = UMBRELLA/'build/preview-iteration-m9uucbpj/audit.json'
    if json.loads(audit.read_text())['fixtures']['160x80.png']!=FIXTURE_HASH:
        raise ValueError('corrected D2 provenance mismatch')
    shutil.copyfile(audit,output/'corrected-D2-audit.json')
    expected = fixture(fixture_path,output/'fixtures')
    save(output/'fixture.json',expected)
    save(output/'fixture-inventory.json',inventory(output/'fixtures'))
    save(output/'schedule.json',a.schedule())
    save(output/'qualification-schedule.json',a.qualification())
    save(output/'policy.json',dict(version=1,maximum_calls=150,qualification_calls=12,
        scheduled_calls=138,retries=0,recovery=False,watchdog_seconds=25,emergency_seconds=5,
        record_limit=a.LIMIT,stderr_bytes=a.BYTE_LIMIT,overhead_limit='11/10',
        gates=['outer median','outer p95','discovery median','discovery p95'],
        scopes=['block 0','block 1','block 2','pooled'],
        assumptions=['no external actor migrates the launcher during discovery'],
        limits=[268435456,64000000,32768,268435456,1048576,67108864,4096],
        operation='inspection',orientation='Apply',metadata=False))
    Run(output).build()
    frozen_names = ['images.tar','provenance.json','policy.json','schedule.json',
                    'qualification-schedule.json','fixture.json','fixture-inventory.json','tooling-inventory.json']
    frozen_names += [v+'/'+name for v in a.VARIANTS for name in ('source-inventory.json','runtime-inventory.json','overlay.patch')]
    save(output/'frozen.json',{name:sha(output/name) for name in frozen_names})
    integrity(output)
    print('Prepared; overlays must be reviewed before --execute.',flush=True)
    return output


def execute(output):
    # Exclusive creation makes this directory single-dispatch, including failed attempts.
    with (output/'execution-started.json').open('x') as f:
        json.dump(dict(started_ns=time.monotonic_ns()),f)
    slots=json.loads((output/'schedule.json').read_text())
    qual=json.loads((output/'qualification-schedule.json').read_text())
    samples, qualifications, stop = [], [], None
    expected=json.loads((output/'fixture.json').read_text())
    try:
        integrity(output)
        if slots!=a.schedule() or qual!=a.qualification():
            raise ValueError('schedule differs from reviewed policy')
        for phase,planned,retained in [('qualification',qual,qualifications),('measurement',slots,samples)]:
            for slot in planned:
                if slot == planned[0] or (phase == 'measurement' and slot['id'] in ('m046','m092')):
                    integrity(output)
                row=dict(slot,qualified=False)
                retained.append(row)
                directory=output/slot['id']
                try:
                    home=output/slot['variant']
                    provenance=json.loads((output/'provenance.json').read_text())['variants'][slot['variant']]
                    if sha(home/'build/scope-discovery-profile') != provenance['binary_sha256']:
                        raise ValueError('binary mutation')
                    result=call(home/'build/scope-discovery-profile',home/'runtime',output/'fixtures/source.png',slot,directory)
                    row['status']=result['status']
                    row['intervals']=validate(slot,result,expected,directory)
                    row['qualified']=True
                    print(slot['id'],slot['variant'],slot['case'],'passed',flush=True)
                except Exception as exc:
                    row['error']=str(exc)
                    raise
                finally:
                    save(output/(phase+'.json'),retained)
            integrity(output)
    except Exception as exc:
        stop=str(exc)
        print('STOP:',stop,flush=True)
    integrity_errors=[]
    try:
        integrity(output)
    except Exception as exc:
        integrity_errors.append(str(exc))
    passed=len(qualifications)==12 and all(q['qualified'] for q in qualifications)
    report=a.summary(slots,samples,qualification_passed=passed and not stop and not integrity_errors)
    report.update(stop=stop,integrity_errors=integrity_errors,qualification_attempted=len(qualifications),
                  qualification_successes=sum(q['qualified'] for q in qualifications),
                  qualification_unattempted=[q for q in qual if q['id'] not in {s['id'] for s in qualifications}])
    save(output/'summary.json',report)
    save(output/'final-integrity.json',dict(passed=not integrity_errors,errors=integrity_errors))
    print(report['verdict'],flush=True)
    return 0 if report['verdict']==a.VERDICT else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',type=Path)
    parser.add_argument('--fixture',type=Path,default=UMBRELLA/'build/preview-experiments-ak2cd2cp/measure-22ulnq_n/fixtures/160x80.png')
    args=parser.parse_args()
    if args.execute:
        return execute(args.execute.resolve())
    prepare(args.fixture)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
