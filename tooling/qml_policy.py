#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate product QML runtime controls; provider templates are exempt."""
from pathlib import Path
import re
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
errors = []
for name in subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0'):
    path = root / name
    if path.suffix != '.qml' or name.startswith(('tests/', 'tooling/')):
        continue
    if root.name == 'holonight-qt' and not name.startswith(('demo/', 'examples/')):
        continue
    for line in path.read_text().splitlines():
        if re.match(r'\s*import\s+(QtQuick.Controls.Basic|Holonight)(\s|$)', line):
            errors.append(f'{name}: concrete runtime style import: {line.strip()}')
        if re.match(r'\s*import\s+QtQuick.Controls(?:\s+\d[\d.]*)?\s*$', line):
            errors.append(f'{name}: QtQuick.Controls needs a namespace alias')
print('\n'.join(errors) if errors else 'QML runtime import policy passed')
sys.exit(bool(errors))
