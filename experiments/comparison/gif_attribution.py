# SPDX-License-Identifier: GPL-3.0-or-later
"""Fixed GIF diagnosis. Candidate qualification never determines diagnostic success."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from animation import encode, reference, patch, fixtures
from harness import Worker
from runtime_bundle import digest, host_environment, prepare
from runtime_evidence import Invocation, destination, require, validate_child
from runtime_trace import analyze

SUITE = 'gif-attribution'


def cases():
    base = dict(patch(0, 0, 3, 2), indices=[1]*6)
    overlay = dict(patch(0, 0, 1, 1), indices=[2])
    tail = dict(patch(2, 1, 1, 1), indices=[3])
    controls = {'opaque': [base, overlay, tail], 'local': [base, dict(overlay, local=True), tail],
                'disposal-2': [base, dict(overlay, disposal=2), tail],
                'disposal-2-local': [base, dict(overlay, disposal=2, local=True), tail],
                'transparent': [base, dict(overlay, transparent=2), tail],
                'disposal-3': [base, dict(overlay, disposal=3), tail],
                'consecutive-3': [base, dict(overlay, disposal=3), dict(tail, disposal=3), overlay]}
    result = [('qt-prefix', 'qt', 256, 128, [patch(0,0,256,128), patch(130,70,64,32,2,None,True,10), patch(143,77,64,32,3,None,False,11)], None, False),
              ('glycin-prefix', 'glycin', 256,128,[patch(0,0,256,128),patch(13,7,64,32,2,None,False,1),patch(26,14,64,32,3,None,False,2)],None,False),
              ('glycin-disposal-2','glycin',12,8,fixtures()['disposal-2'],None,False)]
    result += [('control-'+name, backend,3,2,fs,None,False) for name,fs in controls.items() for backend in ('qt','glycin')]
    full = [dict(patch(0,0,2,2),indices=[i]*4) for i in (1,2)]
    result += [('exhaustion-'+str(repeat),backend,2,2,full,repeat,True) for repeat in (None,2,0) for backend in ('qt','glycin')]
    return result


def definitions():
    pairs = [(f'{backend}-{name}-{trial}', case) for case in cases()
             for name,backend,*_ in [case] for trial in range(3)]
    probes = [(f'decoder-{local}-{trial}', ('control-disposal-2'+('-local' if local else ''), 'decoder',3,2,
                next(c[4] for c in cases() if c[0]=='control-disposal-2'+('-local' if local else '')),None,False))
              for local in (False,True) for trial in range(3)]
    return pairs, probes


def expectations():
    pairs, probes = definitions()
    names = ['oracle','provenance','source-contract','native-build'] + [n for n,_ in pairs+probes]
    needed = {n:dict(artifacts=[n+'.json'],min_scopes=0,scopes=[]) for n in names[:4]}
    for name,case in pairs+probes:
        roles = ('decoder',) if name.startswith('decoder-') else ('raw','wrapper')
        artifacts = [name+'/comparison.json']
        for role in roles:
            artifacts += [f'{name}/{role}/{f}' for f in ('fixture.gif','definition.json','responses.json','findings.json','stderr.txt','worker.trace','worker.trace.json')]
        _,_,w,h,fs,repeat,exhaust=case
        for role in roles:
            for cycle in range(3 if exhaust else 1):
                count=1 if cycle==1 else len(fs)
                for i in range(count+(4 if exhaust and cycle!=1 else 0)):
                    artifacts.append(f'{name}/{role}/{cycle}-{i}-actual.rgba')
                    if i<len(fs):
                        artifacts += [f'{name}/{role}/{cycle}-{i}-{kind}.rgba' for kind in ('expected','difference')]
        needed[name] = dict(artifacts=artifacts,min_scopes=len(roles),scopes=[])
    return names, needed


def write(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data,indent=2)+'\n')


def pixels(want, actual):
    require(len(want)==len(actual), f'pixel length mismatch: {len(want)} != {len(actual)}')
    return bytes(abs(a-b) for a,b in zip(want,actual))


def signature(responses):
    """Compare frame semantics; preserve errors, normalize only documented end fields."""
    result = []
    for q in responses:
        if q['op'] != 'frame':
            continue
        r=q['response']
        outcome=r.get('outcome')
        require(outcome in ('success','end'), r)
        if outcome=='success':
            result.append((outcome,r.get('width'),r.get('height'),r.get('delay_ms',r.get('delay_us',0)/1000),r.get('pixel_sha256')))
        else:
            require(r.get('width',0)==0 and r.get('height',0)==0, r)
            result.append((outcome,0,0,None,r.get('pixel_sha256')))
    require(result, 'missing frame responses')
    return result


def diagnostic_status(findings, equivalent, source_complete):
    require(equivalent, 'raw/wrapper disagreement remains unresolved')
    require(source_complete, 'missing matching source provenance')
    require(all(f.get('complete') is True for f in findings), 'incomplete candidate evidence')
    return dict(status='passed', candidate_qualification='failed' if any(f['qualification']=='failed' for f in findings) else 'passed')


def run(root, build, bundle, role, binary, case, validate):
    name,backend,w,h,fs,repeat,exhaust=case
    root.mkdir(parents=True)
    data=encode(w,h,fs,repeat)
    validate(data,w,h,fs,repeat)
    (root/'fixture.gif').write_bytes(data)
    write(root,'definition.json',dict(width=w,height=h,frames=fs,repeat=repeat))
    responses=[]
    findings=[]
    worker=None
    try:
        worker=Worker(build/binary,runtime_bundle=bundle,glycin=backend=='glycin',trace=root/'worker.trace')
        def request(op, **kw):
            r=worker.request(op,**kw)
            p=bytes(r.pop('pixels',[]))
            responses.append(dict(op=op,fields={k:v for k,v in kw.items() if k!='payload'},response=r))
            return r,p
        def load(op):
            r,_=request(op,**({'payload':data} if op=='load' else {}))
            require(r['outcome']==('success' if binary=='qt-worker' and op=='restart' else 'loaded'),r)
            if binary=='qt-worker':
                r,_=request('gif-open'); require(r['outcome']=='success',r)
        load('load')
        expected=list(reference(w,h,fs))
        for cycle in range(3 if exhaust else 1):
            if cycle: load('restart')
            count=1 if cycle==1 else len(fs)
            for i in range(count+(4 if exhaust and cycle!=1 else 0)):
                r,p=request('frame',width=w,height=h,capture_pixels=True)
                label=f'{cycle}-{i}'
                (root/(label+'-actual.rgba')).write_bytes(p)
                if i<len(fs):
                    want=expected[i]
                    (root/(label+'-expected.rgba')).write_bytes(want)
                    (root/(label+'-difference.rgba')).write_bytes(pixels(want,p))
                    require(r['outcome']=='success',r)
                    failed=p!=want or (r.get('width'),r.get('height'))!=(w,h) or r.get('delay_ms',r.get('delay_us',0)/1000)!=(30,70,110)[i%3]
                else:
                    require(r['outcome'] in ('success','end'),r)
                    failed=r['outcome']!='end'
                findings.append(dict(cycle=cycle,index=i,complete=True,qualification='failed' if failed else 'passed'))
    finally:
        if worker:
            (root/'stderr.txt').write_text(worker.close())
        write(root,'responses.json',responses)
        write(root,'findings.json',findings)
        if (root/'worker.trace').exists():
            write(root,'worker.trace.json',analyze((root/'worker.trace').read_text(),cwd=str(Path.cwd())))
    return responses,dict(complete=True,qualification='failed' if any(f['qualification']=='failed' for f in findings) else 'passed')


def execute(args):
    spec=importlib.util.spec_from_file_location('triage',Path(__file__).with_name('animation-triage.py'))
    triage=importlib.util.module_from_spec(spec); spec.loader.exec_module(triage)
    build=args.build.resolve()
    root=destination(args,build,'gif-attribution-')
    names,needed=expectations()
    inv=Invocation(root,SUITE,{},names,needed)
    records=[dict(name=n,status='not-run') for n in names]
    inv.report['records']=records
    def scenario(name, function):
        inv.scenario(name)
        record=next(r for r in records if r['name']==name)
        try:
            extra=function() or {}
            record.update(status='passed')
            record.update(extra)
        except Exception as error:
            record.update(status='failed',error=repr(error))
        inv.checkpoint()
        return record['status']=='passed'
    def oracle():
        triage.self_checks(); write(root,'oracle.json',dict(status='passed'))
    scenario('oracle',oracle)
    # Provenance is deliberately fail closed: source preparation is independent of candidate pixels.
    from gif_provenance import collect
    scenario('provenance',lambda: collect(build,root))
    def contract():
        source=json.loads((root/'provenance.json').read_text())
        write(root,'source-contract.json',dict(source_complete=source.get('source_complete'),blocker=source.get('blocker'),attributions=source.get('attributions')))
        require(source.get('source_complete') is True,'matching sources, patches, lockfile or source audit unavailable')
    complete=scenario('source-contract',contract)
    bundle=build/(root.name+'-runtime-bundle')
    def native():
        commands=[['cmake','--build',str(build),'--target','qt-worker','glycin-worker','qt-animation-repro'],
                  ['cargo','build','--release','--locked','--offline','--manifest-path',str(Path(__file__).parent/'rust/Cargo.toml'),'--target-dir',str(build/'rust')]]
        logs=[]
        for command in commands:
            r=subprocess.run(command,capture_output=True,text=True,timeout=120,env=host_environment())
            logs.append(dict(command=command,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
            write(root,'native-build.json',logs)
            require(r.returncode==0,'host-native build failed')
        import shutil
        shutil.copy2(build/'rust/release/animation-repro',build/'glycin-animation-repro')
        decoder=build.parent/'gif-decoder'
        r=subprocess.run(['cargo','build','--release','--locked','--offline','--manifest-path',str(decoder/'Cargo.toml')],capture_output=True,text=True,timeout=120)
        write(root,'decoder-build.json',dict(command=r.args,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        require(r.returncode==0,'exact decoder build unavailable')
        shutil.copy2(decoder/'target/release/gif-decoder-repro',build/'gif-decoder-repro')
        for name in ('src/main.rs','Cargo.toml','Cargo.lock'):
            path=decoder/name
            write(root,'decoder-'+Path(name).name+'.json',dict(path=str(path),sha256=digest(path)))
        from gif_provenance import audit_decoder
        audit_decoder(build,root)
        prepare(build,bundle,[(build/'qt-animation-repro','qt'),(build/'glycin-animation-repro','glycin'),(build/'gif-decoder-repro','qt')])
        write(root,'bundle-manifest.json',json.loads((bundle/'manifest.json').read_text()))
    native_ok=scenario('native-build',native) if complete else False
    if not complete:
        next(r for r in records if r['name']=='native-build')['reason']='source contract unresolved; native execution not run'
    if native_ok and complete:
        pairs,probes=definitions()
        for name,case in pairs:
            def paired(name=name,case=case):
                backend=case[1]
                a,af=run(root/name/'raw',build,bundle,'raw',backend+'-animation-repro',case,triage.validate)
                b,bf=run(root/name/'wrapper',build,bundle,'wrapper',backend+'-worker',case,triage.validate)
                equivalent=signature(a)==signature(b)
                comparison=dict(equivalent=equivalent,findings=[af,bf])
                write(root,name+'/comparison.json',comparison)
                return diagnostic_status([af,bf],equivalent,complete)
            scenario(name,paired)
        for name,case in probes:
            def decoder_probe(name=name,case=case):
                responses,finding=run(root/name/'decoder',build,bundle,'decoder','gif-decoder-repro',case,triage.validate)
                global_case='glycin-'+case[0]+'-0'
                loader=json.loads((root/global_case/'raw/responses.json').read_text())
                equivalent=signature(responses)==signature(loader)
                write(root,name+'/comparison.json',dict(equivalent=equivalent,findings=[finding]))
                return diagnostic_status([finding],equivalent,complete)
            scenario(name,decoder_probe)
    ok=inv.finish(records,not_run=[r['name'] for r in records if r['status']=='not-run'],candidate_qualification='failed' if any(r.get('candidate_qualification')=='failed' for r in records) else 'passed' if complete and all(r['status']=='passed' for r in records) else 'unresolved')
    if ok:
        check=subprocess.run([sys.executable,str(Path(__file__)),str(root)],capture_output=True,text=True)
        if check.returncode!=0:
            inv.report.update(status='failed',independent_validation_error=check.stderr)
            inv.checkpoint()
            ok=False
    print(root,flush=True)
    return 0 if ok else 1


def validate_completed(root):
    names,needed=expectations()
    report=validate_child(root,suite=SUITE,options={},required=names,requirements=needed)
    from runtime_evidence import artifact_path
    decoder=json.loads(artifact_path(root,'decoder-contract.json').read_text())
    require(decoder.get('default_features') is False and decoder.get('packages'),'missing decoder graph proof')
    provenance=json.loads((root/'provenance.json').read_text())
    require(provenance.get('source_complete') is True,'missing source provenance')
    for source_ref in provenance['attributions']['references']:
        path=artifact_path(root,source_ref['file'])
        lines=path.read_text().splitlines()
        require(all(source_ref['pattern'] in lines[n-1] for n in source_ref['lines']),'altered source reference')
    require(len(report['scopes'])==144,'expected 144 worker scopes')
    pairs,probes=definitions()
    findings=[]
    for name,case in pairs+probes:
        comparison=json.loads((root/name/'comparison.json').read_text())
        require(comparison.get('equivalent') is True,'unresolved comparison')
        findings += comparison['findings']
        roles=('decoder',) if name.startswith('decoder-') else ('raw','wrapper')
        responses=[]
        for role in roles:
            directory=root/name/role
            sequence=json.loads((directory/'responses.json').read_text())
            responses.append(signature(sequence))
            for expected in directory.glob('*-expected.rgba'):
                actual=expected.with_name(expected.name.replace('-expected','-actual')).read_bytes()
                difference=expected.with_name(expected.name.replace('-expected','-difference')).read_bytes()
                require(difference==pixels(expected.read_bytes(),actual),'invalid difference pixels')
        if len(responses)==2:
            require(responses[0]==responses[1],'raw/wrapper mismatch')
    # Recompute qualification from retained pixels and every frame response.
    recomputed=[]
    for name,case in pairs+probes:
        _,_,w,h,fs,repeat,exhaust=case
        roles=('decoder',) if name.startswith('decoder-') else ('raw','wrapper')
        for role in roles:
            directory=root/name/role
            require((directory/'fixture.gif').read_bytes()==encode(w,h,fs,repeat),'altered fixture')
            sequence=[q['response'] for q in json.loads((directory/'responses.json').read_text()) if q['op']=='frame']
            count=sum((1 if cycle==1 else len(fs))+(4 if exhaust and cycle!=1 else 0) for cycle in range(3 if exhaust else 1))
            require(len(sequence)==count,'incomplete response sequence')
            expected=list(reference(w,h,fs))
            failed=False
            index=0
            for cycle in range(3 if exhaust else 1):
                count=(1 if cycle==1 else len(fs))+(4 if exhaust and cycle!=1 else 0)
                for i in range(count):
                    response=sequence[index]; index+=1
                    actual=(directory/f'{cycle}-{i}-actual.rgba').read_bytes()
                    import hashlib
                    require(response.get('pixel_sha256')==(hashlib.sha256(actual).hexdigest() if actual else None),'response pixel hash mismatch')
                    if i<len(fs):
                        want=(directory/f'{cycle}-{i}-expected.rgba').read_bytes()
                        require(want==expected[i],'altered oracle pixels')
                        pixels(want,actual)
                        failed |= actual!=want or (response.get('width'),response.get('height'))!=(w,h) or response.get('delay_ms',response.get('delay_us',0)/1000)!=(30,70,110)[i%3]
                    else:
                        failed |= response['outcome']!='end'
            recomputed.append(dict(complete=True,qualification='failed' if failed else 'passed'))
    require(recomputed==findings,'candidate findings disagree with pixels/responses')
    status=diagnostic_status(recomputed,True,True)
    require(report['candidate_qualification']==status['candidate_qualification'],'qualification findings hidden')
    return report


if __name__=='__main__':
    validate_completed(Path(sys.argv[1]))
