# SPDX-License-Identifier: GPL-3.0-or-later
"""Retain regular provenance artifacts; extracted upstream trees stay in scratch."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tomllib

from runtime_bundle import PLUGINS, EXECUTABLES, digest, host_environment
from runtime_evidence import require


def collect(build, root):
    scratch=build.parent/'gif-sources'
    target=root/'sources'
    target.mkdir(exist_ok=True)
    commands=[]
    source_mismatches=[]
    files={}
    evidence=dict(source_complete=False,commands=commands,files=files,
                  loader_graph='sources/loader-Cargo.lock',client_graph='sources/client-Cargo.lock')
    def save():
        (root/'provenance.json').write_text(json.dumps(evidence,indent=2)+'\n')
    def command(args):
        r=subprocess.run(args,capture_output=True,text=True,timeout=120,env=host_environment())
        commands.append(dict(command=args,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr))
        save()
        require(r.returncode==0,commands[-1])
        return r.stdout
    def retain(path,name):
        require(path.is_file(),'missing matching source: '+str(path))
        shutil.copyfile(path,target/name)
        files[name]=dict(origin=str(path),sha256=digest(target/name))
        save()
        return (target/name).read_text(errors='replace')
    save()
    try:
        versions=command(['pacman','-Q','qt6-base','qt6-imageformats','glycin'])
        require(versions=='qt6-base 6.12.0-3\nqt6-imageformats 6.12.0-1\nglycin 2.2.6-1\n','installed baseline changed')
        for binary in [*PLUGINS,*EXECUTABLES]:
            command(['pacman','-Qo',binary])
            command(['readelf','-n',binary])
            files[binary]=dict(sha256=digest(Path(binary)))
        for package,version in [('glycin','2.2.6-1'),('qt6-base','6.12.0-3'),('qt6-imageformats','6.12.0-1')]:
            command(['pacman','-Qi',package])
            archive=Path('/var/cache/pacman/pkg')/f'{package}-{version}-x86_64.pkg.tar.zst'
            files[str(archive)]=dict(sha256=digest(archive))
            for member in ('.BUILDINFO','.PKGINFO'):
                (target/(package+member)).write_text(command(['bsdtar','-xOf',str(archive),member]))
            retain(scratch/(package+'.PKGBUILD'),package+'.PKGBUILD')
            require('pkgbuild_sha256sum = '+digest(target/(package+'.PKGBUILD')) in (target/(package+'.BUILDINFO')).read_text(),'recipe does not match package build metadata')
            members={'glycin':'usr/lib/glycin-loaders/2+/glycin-image-rs','qt6-base':'usr/lib/qt6/plugins/imageformats/libqgif.so'}
            if package in members:
                member=members[package]
                raw=subprocess.run(['bsdtar','-xOf',str(archive),member],capture_output=True,timeout=120,check=True).stdout
                require(hashlib.sha256(raw).hexdigest()==digest(Path('/'+member)),'installed binary differs from package')
        patches=['qt6-base-cflags.patch','qt6-base-nostrip.patch','e320c929.patch','032643f9.patch','6b7ee05d.patch']
        recipe=(target/'qt6-base.PKGBUILD').read_text()
        for name in patches:
            text=retain(scratch/name,name)
            require('diff --git ' in text,'invalid patch '+name)
            require('src/plugins/imageformats/gif/' not in text,'GIF source modified by distribution patch')
            if name.startswith('qt6-base-'):
                require(digest(target/name) in recipe,'distribution patch hash mismatch')
            else:
                require(text.startswith('From '+name.split('.')[0]),'patch commit identity mismatch')
        for repo,commit in [('qtbase','025bdad181de241e81bf853c8a2d7bf3d19261a9'),('qtimageformats','dc13f2fbff1d579cfb2eb2d9092e3563b4d05b8e')]:
            require(command(['git','-C',str(scratch/repo),'rev-parse','v6.12.0^{commit}']).strip()==commit,'Qt tag mismatch')
            require(not command(['git','-C',str(scratch/repo),'status','--porcelain']).strip(),'modified upstream checkout')
            archive=scratch/(repo+'-recipe.tar')
            args=['git','-c','core.abbrev=no','-C',str(scratch/repo),'archive','--format','tar','v6.12.0']
            with archive.open('wb') as output:
                result=subprocess.run(args,stdout=output,stderr=subprocess.PIPE,timeout=120,check=True)
            checksum=digest(archive)
            expected={'qtbase':'d97ef157dc50bdf0425337e9adede8135ab508a4ab2f1abae7e9cfc42c5f86db','qtimageformats':'30226a5944388a918e925127d8f90486d36027567a6cb058ae52b40cab86c64b'}[repo]
            files[str(archive)]=dict(sha256=checksum,recipe_sha256=expected)
            commands.append(dict(command=args,returncode=result.returncode,stdout_file=str(archive),stderr=result.stderr.decode()))
            if checksum!=expected:
                source_mismatches.append(dict(repository=repo,expected=expected,actual=checksum,method='makepkg calc_checksum_git: git -c core.abbrev=no archive --format tar tag'))
        args=['git','-c','core.abbrev=no','-C',str(scratch/'glycin-git'),'archive','--format','tar','2.2.6']
        archive=scratch/'glycin-recipe.tar'
        with archive.open('wb') as output:
            subprocess.run(args,stdout=output,stderr=subprocess.PIPE,timeout=120,check=True)
        with archive.open('rb') as source:
            checksum=hashlib.file_digest(source,'blake2b').hexdigest()
        require(checksum in (target/'glycin.PKGBUILD').read_text(),'Glycin recipe source archive checksum mismatch')
        files[str(archive)]=dict(blake2b=checksum,recipe_match=True)
        commands.append(dict(command=args,returncode=0,stdout_file=str(archive)))
        for path in ('Cargo.lock','glycin-loaders/glycin-image-rs/src/lib.rs','glycin-loaders/glycin-image-rs/src/animated.rs'):
            require((scratch/'glycin-git'/path).read_bytes()==(scratch/'glycin-2.2.6'/path).read_bytes(),'Glycin Git/archive content mismatch')
        qt=retain(scratch/'qtbase/src/plugins/imageformats/gif/qgifhandler.cpp','qgifhandler.cpp')
        loader=scratch/'glycin-2.2.6'
        for path,name in [('Cargo.lock','loader-Cargo.lock'),('Cargo.toml','loader-Cargo.toml'),
                          ('glycin-loaders/glycin-image-rs/Cargo.toml','image-rs-Cargo.toml'),
                          ('glycin-loaders/glycin-image-rs/src/lib.rs','loader-lib.rs'),
                          ('glycin-loaders/glycin-image-rs/src/animated.rs','loader-animated.rs')]:
            retain(loader/path,name)
        retain(scratch/'glycin-2.2.6.tar.gz','glycin-2.2.6.tar.gz')
        image=retain(scratch/'image-0.25.10/src/codecs/gif.rs','image-gif.rs')
        retain(scratch/'image-0.25.10.crate','image-0.25.10.crate')
        lock=tomllib.loads((target/'loader-Cargo.lock').read_text())
        image_package=next(p for p in lock['package'] if p['name']=='image')
        require(image_package['version']=='0.25.10' and image_package['checksum']==digest(target/'image-0.25.10.crate'),'decoder archive mismatch')
        client=next(Path.home().glob('.cargo/registry/src/*/glycin-3.1.0'))
        retain(client/'src/api_loader.rs','client-api_loader.rs')
        retain(client/'.cargo_vcs_info.json','client-vcs.json')
        client_tree=scratch/'glycin-215113448d88270d45ae9a095eb14a983a765650'
        require((client_tree/'glycin/src/api_loader.rs').read_bytes()==(client/'src/api_loader.rs').read_bytes(),'published client/source commit mismatch')
        for path,name in [('tests/tests.rs','client-tests.rs')]:
            retain(client_tree/path,name)
        retain(loader/'tests/processor-loader.rs','loader-tests.rs')
        retain(loader/'glycin-loaders/meson.build','loader-meson.build')
        retain(loader/'glycin-utils/Cargo.toml','loader-utils-Cargo.toml')
        retain(scratch/'glycin-client.tar.gz','glycin-client.tar.gz')
        # Verify extracted loader and decoder inputs against the downloaded archives.
        for archive,paths,prefix in [(scratch/'glycin-2.2.6.tar.gz', ['Cargo.lock','Cargo.toml','glycin-loaders/glycin-image-rs/src/lib.rs','glycin-loaders/glycin-image-rs/src/animated.rs','glycin-loaders/glycin-image-rs/Cargo.toml'], 'glycin-2.2.6'),(scratch/'image-0.25.10.crate',['src/codecs/gif.rs'],'image-0.25.10')]:
            with tarfile.open(archive) as source:
                for path in paths:
                    require(source.extractfile(prefix+'/'+path).read()==(scratch/prefix/path).read_bytes(),'extracted source differs from archive')
        retain(client/'src/dbus.rs','client-dbus.rs')
        retain(Path(__file__).parent/'rust/Cargo.lock','client-Cargo.lock')
        # Keep exact source lines supporting the call chain, not inferred ownership from pixels alone.
        queries={'qgifhandler.cpp':['color(bgcol)','lcmap ? localcmap : globalcmap'],
                 'loader-lib.rs':['GifDecoder::new(data)','Self::Gif(d) => Some(d.into_frames())','!frame_request.loop_animation','return Err(ProcessError::NoMoreFrames)'],
                 'loader-animated.rs':['.into_frames()','looped = true','buffer.into_raw()'],
                 'image-gif.rs':['intentionally ignore the background color','DisposalMethod::Background'],
                 'client-api_loader.rs':['pub async fn specific_frame','Controls if first frame is returned after last frame'],
                 'client-tests.rs':['loop_animation(false)'], 'loader-tests.rs':['loop_animation(false)']}
        references=[]
        for name,patterns in queries.items():
            lines=(target/name).read_text().splitlines()
            for pattern in patterns:
                matches=[i+1 for i,line in enumerate(lines) if pattern in line]
                require(matches,'source chain missing: '+pattern)
                references.append(dict(file='sources/'+name,lines=matches,pattern=pattern))
        evidence['retrieval'] = dict(timeout_seconds=120,
            recipes=[f'https://gitlab.archlinux.org/archlinux/packaging/packages/{package}/-/raw/{version}/PKGBUILD' for package,version in [('glycin','2.2.6-1'),('qt6-base','6.12.0-3'),('qt6-imageformats','6.12.0-1')]],
            archives=['https://gitlab.gnome.org/GNOME/glycin/-/archive/2.2.6/glycin-2.2.6.tar.gz','https://static.crates.io/crates/image/image-0.25.10.crate','https://gitlab.gnome.org/GNOME/glycin/-/archive/215113448d88270d45ae9a095eb14a983a765650/glycin-215113448d88270d45ae9a095eb14a983a765650.tar.gz'],
            qt=['git clone --depth 1 --branch v6.12.0 https://code.qt.io/qt/'+repo+'.git' for repo in ('qtbase','qtimageformats')],
            attempts=['local package cache: exact binary packages found; no loader decoder sources', 'local Cargo cache: exact client source found; image 0.25.10 initially unavailable', 'sandbox DNS resolution failed; authorized external retrieval succeeded', 'code.qt.io cgit snapshot endpoints returned HTTP 400; exact recipe git tags retrieved instead'])
        evidence.update(source_complete=not source_mismatches,source_checksum_mismatches=source_mismatches,attributions=dict(references=references,
            qt='Qt GIF disposal-2 selects active local table; distribution patches do not modify GIF decoder.',
            glycin_pixels='image 0.25.10 composited GIF API deliberately ignores logical background; loader forwards these buffers.',
            exhaustion='Loader resumes animation and rejects looped frame zero only. Client docs control crossing the last frame; persistent exhaustion is an application requirement, not an established upstream guarantee.'))
        require(not source_mismatches,'distribution source archive checksums do not match; source identity remains unresolved')
    except Exception as error:
        evidence['blocker']=repr(error)
        save()
        raise
    save()


def audit_decoder(build,root):
    """Check the exact image feature set and its transitive locked package identities."""
    decoder=build.parent/'gif-decoder'
    loader=build.parent/'gif-sources/glycin-2.2.6'
    manifest=tomllib.loads((decoder/'Cargo.toml').read_text())
    expected=tomllib.loads((loader/'glycin-loaders/glycin-image-rs/Cargo.toml').read_text())['dependencies']['image']['features']
    image=manifest['dependencies']['image']
    require(image['version']=='=0.25.10' and image['default-features'] is False and sorted(image['features'])==sorted(expected),'decoder feature mismatch')
    original=tomllib.loads((loader/'Cargo.lock').read_text())['package']
    actual=tomllib.loads((decoder/'Cargo.lock').read_text())['package']
    def graph(packages, start="image", version="0.25.10"):
        output={}
        def visit(name,version=None):
            candidates=[p for p in packages if p['name']==name and (version is None or p['version']==version)]
            require(len(candidates)==1,'ambiguous decoder dependency '+name)
            p=candidates[0]
            key=p['name']+' '+p['version']
            if key in output: return
            output[key]=dict(checksum=p.get('checksum'),source=p.get('source'))
            for dependency in p.get('dependencies',[]):
                parts=dependency.split()
                visit(parts[0],parts[1] if len(parts)>1 else None)
        visit(start,version)
        return output
    expected_graph,actual_graph=graph(original),graph(actual)
    require(all(expected_graph.get(key)==value for key,value in actual_graph.items()),'decoder package identity differs from installed loader lock')
    require(graph(original,'gif','0.14.2')==graph(actual,'gif','0.14.2'),'GIF decoder graph differs from loader lock')
    data=dict(features=sorted(expected),default_features=False,packages=actual_graph,
              loader_lock_only=sorted(set(expected_graph)-set(actual_graph)),
              graph_note='Loader workspace lock includes optional feature edges for other formats. All probe package identities and the complete GIF graph match; image feature flags match the loader manifest.',
              inputs={str(p):digest(p) for p in (decoder/'Cargo.toml',decoder/'Cargo.lock',decoder/'src/main.rs',decoder/'target/release/gif-decoder-repro')})
    (root/'decoder-contract.json').write_text(json.dumps(data,indent=2)+'\n')
    return data
