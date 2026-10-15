#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the repository's acceptance entry point in its pinned Docker image."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def run(*args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def snapshot(source, target, pinned_submodules=False):
    """Copy current tracked and unignored files, including edits, without host builds."""
    target.mkdir(parents=True)
    names = subprocess.check_output(['git', '-C', str(source), 'ls-files', '-z',
                                     '--cached', '--others', '--exclude-standard']).split(b'\0')
    for raw in set(names) - {b''}:
        path = Path(os.fsdecode(raw))
        original = source / path
        if original.is_file() or original.is_symlink():
            destination = target / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, destination, follow_symlinks=False)
    submodules = []
    if (source / '.gitmodules').exists():
        links = subprocess.check_output(['git', '-C', str(source), 'ls-tree', 'HEAD'], text=True)
        for line in links.splitlines():
            mode, kind, revision, name = line.split()
            if mode != '160000':
                continue
            submodules.append((name, revision))
            if pinned_submodules:
                child = target / name
                child.mkdir()
                archive = subprocess.Popen(['git', '-C', str(source / name), 'archive', revision], stdout=subprocess.PIPE)
                result = subprocess.run(['tar', '-x', '-C', str(child)], stdin=archive.stdout)
                archive.stdout.close()
                if archive.wait() or result.returncode:
                    raise RuntimeError(f'Initialize umbrella gitlink {name} at {revision}')
                run('git', 'init', '-q', child)
                run('git', '-C', child, 'add', '-A', '--force')
            else:
                snapshot(source / name, target / name)
    # A local index supports source inventories and REUSE without mounting host .git.
    run('git', 'init', '-q', target)
    run('git', '-C', target, 'add', '-A', '--force', '--', '.', *(f':(exclude){name}' for name, _ in submodules))
    for name, revision in submodules:
        run('git', '-C', target, 'update-index', '--add', '--cacheinfo', f'160000,{revision},{name}')


def providers(destination, siblings):
    cache = ROOT / 'build/sources'
    cache.mkdir(parents=True, exist_ok=True)
    for provider in json.loads((ROOT / 'scripts/ci/providers.json').read_text()):
        name, revision = provider['name'], provider['revision']
        print(f'Provider: {name} {revision}' if not siblings else f'Provider: {name} (current sibling)', flush=True)
        if not re.fullmatch(r'[a-z0-9-]+', name) or not re.fullmatch(r'[0-9a-f]{40}', revision):
            raise ValueError('Provider names and full source revisions are required')
        if siblings:
            print(f'Using current sibling checkout: {siblings / name}', flush=True)
            snapshot(siblings / name, destination / name)
        else:
            checkout = cache / f'{name}-{revision}'
            if not checkout.exists():
                temporary = Path(tempfile.mkdtemp(prefix=name + '-', dir=cache))
                run('git', 'init', '-q', temporary)
                run('git', '-C', temporary, 'fetch', '--depth=1',
                    f'https://github.com/lebedenko/{name}.git', revision)
                run('git', '-C', temporary, 'checkout', '--detach', 'FETCH_HEAD')
                temporary.rename(checkout)
            actual = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
            if actual != revision:
                raise ValueError(f'Wrong cached source revision for {name}: {actual}')
            # Export committed content; local edits in the source cache never enter acceptance.
            exported = destination / name
            exported.mkdir(parents=True)
            archive = subprocess.Popen(['git', '-C', str(checkout), 'archive', revision], stdout=subprocess.PIPE)
            result = subprocess.run(['tar', '-x', '-C', str(exported)], stdin=archive.stdout)
            archive.stdout.close()
            if archive.wait() or result.returncode:
                raise RuntimeError(f'Cannot export {name}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check', 'integration', 'format'], default='check', nargs='?')
    parser.add_argument('--siblings', type=Path, help='Explicitly test current provider checkouts, including edits')
    args = parser.parse_args()
    image = (ROOT / 'scripts/ci/image.txt').read_text().strip()
    if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}', image):
        parser.error('scripts/ci/image.txt must pin an image digest')
    for tool in ('docker', 'git', 'tar'):
        if not shutil.which(tool):
            parser.error(f'Missing required launcher tool: {tool}')
    if subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode:
        run('docker', 'pull', '--platform', 'linux/amd64', image)
    output = ROOT / 'build/acceptance'
    output.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=args.mode + '-', dir=output))
    print(f'Image: {image}\nAcceptance output: {work}', flush=True)
    snapshot(ROOT, work / 'source', pinned_submodules=not bool(args.siblings))
    (work / 'providers').mkdir()
    if args.mode != 'format':
        providers(work / 'providers', args.siblings.resolve() if args.siblings else None)
    if os.getuid() == 0:
        parser.error('Run acceptance as an ordinary host user; permission regressions require it')
    (work / 'passwd').write_text(f'root:x:0:0:root:/root:/bin/bash\nalpm:x:979:979:Arch Linux Package Management:/:/usr/bin/nologin\nci:x:{os.getuid()}:{os.getgid()}:CI:/work/home:/bin/bash\nnobody:x:65534:65534:nobody:/:/usr/bin/nologin\n')
    (work / 'group').write_text(f'root:x:0:\nalpm:x:979:\nci:x:{os.getgid()}:\nnobody:x:65534:\n')
    command = ['docker', 'run' , '--rm', '--platform', 'linux/amd64', '--network=none',
               '--user', f'{os.getuid()}:{os.getgid()}',
               '--mount', f'type=bind,src={work},dst=/work',
               '--mount', f'type=bind,src={work / "passwd"},dst=/etc/passwd,readonly',
               '--mount', f'type=bind,src={work / "group"},dst=/etc/group,readonly',
               '--workdir', '/work/source', '--env', f'HOLONIGHT_CI_IMAGE={image}',
               '--env', f'JOBS={os.environ.get("JOBS", "2")}',
               '--entrypoint', 'bash', image, 'scripts/ci/entry.sh', args.mode]
    with (work / 'acceptance.log').open('w') as log:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
        status = process.wait()
    if status:
        raise SystemExit(status)
    if args.mode == 'format':
        # Only copy back files changed by the formatter, preserving the caller's other edits.
        changed = subprocess.check_output(['git', '-C', str(work / 'source'), 'diff', '--name-only', '-z'])
        for raw in changed.split(b'\0'):
            if raw:
                path = Path(os.fsdecode(raw))
                shutil.copy2(work / 'source' / path, ROOT / path)
    if args.mode == 'integration' and (ROOT / 'scripts/ci/runtime.py').exists():
        run('python3', ROOT / 'scripts/ci/runtime.py', image, work)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'Acceptance failed: {error}') from error
