#!/usr/bin/env python3
"""Run push validation against isolated current working-tree inputs."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
LANES = ('build-test',)


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def snapshot(destination):
    tracked = git('ls-files', '-z').split(b'\0')
    new = git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0')
    for raw in dict.fromkeys(tracked + new):
        if not raw:
            continue
        name = os.fsdecode(raw)
        source = ROOT / name
        if source.is_symlink() or source.is_file():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target, follow_symlinks=False)
        elif source.exists():
            raise RuntimeError(f'Unsupported snapshot input: {name}')
    return [os.fsdecode(raw) for raw in new if raw]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lane', choices=LANES, action='append')
    args = parser.parse_args()
    output = ROOT / 'build' / 'ci'
    output.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), dir=output))
    print(f'CI logs: {output}', flush=True)
    report = {'revision': git('rev-parse', 'HEAD').decode().strip(),
              'status': git('status', '--porcelain=v1', '-z').decode(errors='surrogateescape'),
              'platform': 'linux/amd64', 'lanes': {}}
    report['dirty'] = bool(report['status'])
    failed = False
    try:
        runtime = shutil.which('docker') or shutil.which('podman')
        if not runtime:
            raise RuntimeError('Neither Docker nor Podman is available; install a container runtime.')
        report['runtime'] = subprocess.check_output([runtime, '--version'], text=True).strip()
        images = json.loads((ROOT / 'scripts/ci/images.json').read_text())
        with tempfile.TemporaryDirectory(prefix='holonight-images-ci-') as temporary:
            source = Path(temporary) / 'source'
            source.mkdir()
            report['untracked_inputs'] = snapshot(source)
            if report['untracked_inputs']:
                print('Untracked inputs included; add before pushing:')
                for name in report['untracked_inputs']:
                    print(f'  {name!r}')
            for lane in args.lane or LANES:
                image = images['build']
                command = [runtime, 'run', '--rm', '--platform', report['platform'], '--user', f'{os.getuid()}:{os.getgid()}',
                           '--mount', f'type=bind,src={source},dst=/input,readonly',
                           '--tmpfs', '/work:rw,exec,mode=1777', '--workdir', '/work',
                           '--entrypoint', '/bin/sh', image, '/input/scripts/ci/lane.sh', lane]
                print(f'Running {lane}: {image}', flush=True)
                with (output / f'{lane}.log').open('w') as log:
                    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
                report['lanes'][lane] = {'image': image, 'exit_code': result.returncode}
                print(f'{lane}: {"PASS" if result.returncode == 0 else "FAIL"} (see {output / (lane + ".log")})', flush=True)
                if result.returncode != 0:
                    print((output / f'{lane}.log').read_text(errors='replace'), flush=True)
                failed |= result.returncode != 0
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        report['error'] = str(error)
        print(f'CI failed: {error}', file=sys.stderr)
        failed = True
    finally:
        (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
