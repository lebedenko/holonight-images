#!/usr/bin/env python3
"""Extract checksum-pinned supplemental tools into the disposable CI prefix."""
import hashlib
import json
from pathlib import Path
import subprocess

prefix = Path('/work/tools')
prefix.mkdir()
for package in json.loads(Path('scripts/ci/packages.json').read_text()):
    archive = prefix / (package['name'] + '.pkg.tar.zst')
    print(f"Supplement: {package['name']} {package['version']} sha256:{package['sha256']}", flush=True)
    subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '60',
                    '--retry', '2', package['url'], '--output', str(archive)], check=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != package['sha256']:
        raise RuntimeError(f"Archive checksum mismatch: {package['name']}")
    subprocess.run(['bsdtar', '-xf', str(archive), '-C', str(prefix)], check=True)
