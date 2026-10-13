#!/usr/bin/env python3
"""Regression checks for source isolation and required lane failures."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('launcher', Path(__file__).with_name('run.py'))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'repo with spaces'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        for name in ('edited', 'deleted', 'space name', 'executable'):
            (self.root / name).write_text('original')
        (self.root / 'executable').chmod(0o755)
        (self.root / 'link').symlink_to('edited')
        (self.root / '.gitignore').write_text('ignored\nbuild/\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                        'commit', '-qm', 'fixture'], check=True)
        self.real_root = launcher.ROOT
        self.patcher = patch.object(launcher, 'ROOT', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def prepare_fixture(self):
        for name in (*launcher.PREPARATION_INPUTS, 'scripts/ci/images.json'):
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((self.real_root / name).read_bytes())
        prepared = self.root / 'build/ci-prepared'
        prepared.mkdir(parents=True)
        for name in ('packages.txt', 'compiler.txt', 'cmake.txt', 'versions.txt', 'external-state.json', 'reuse.txt'):
            (prepared / name).write_text('fixture environment')
        images = json.loads((self.root / 'scripts/ci/images.json').read_text())
        identity = launcher.preparation_identity(images)
        (prepared / 'manifest.json').write_text(json.dumps({'identity': identity, 'environment': launcher.environment_identity(prepared)}))
        return prepared

    def test_missing_preparation_launches_no_container(self):
        prepared = self.prepare_fixture()
        (prepared / 'manifest.json').unlink()
        with patch.object(launcher.shutil, 'which', return_value='docker'), \
             patch.object(launcher.subprocess, 'check_output', side_effect=lambda *args, **kw: 'fixture' if kw.get('text') else b'fixture'), \
             patch.object(launcher.subprocess, 'run') as run, patch('sys.argv', ['ci']):
            self.assertEqual(launcher.main(), 1)
            run.assert_not_called()

    def test_incompatible_preparation_launches_no_container(self):
        self.prepare_fixture()
        (self.root / 'tooling/VERSION').write_text('incompatible')
        with patch.object(launcher.shutil, 'which', return_value='docker'), \
             patch.object(launcher.subprocess, 'check_output', side_effect=lambda *args, **kw: 'fixture' if kw.get('text') else b'fixture'), \
             patch.object(launcher.subprocess, 'run') as run, patch('sys.argv', ['ci']):
            self.assertEqual(launcher.main(), 1)
            run.assert_not_called()

    def test_tampered_environment_is_rejected(self):
        prepared = self.prepare_fixture()
        (prepared / 'packages.txt').write_text('tampered')
        images = json.loads((self.root / 'scripts/ci/images.json').read_text())
        with self.assertRaisesRegex(RuntimeError, 'evidence changed'):
            launcher.validate_prepared(prepared, launcher.preparation_identity(images))

    def test_explicit_preparation_archives_incompatible_artifacts(self):
        prepared = self.prepare_fixture()
        (prepared / 'inputs.json').write_text('{"incompatible":true}')
        (prepared / 'keep-me').write_text('old evidence')
        runtime = Path(self.temporary.name) / 'docker'
        runtime.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\n'
                           'if sys.argv[1] == "--version": print("fake-runtime")\n'
                           'if sys.argv[1] == "run":\n'
                           ' for argument in sys.argv[1:]:\n'
                           '  if "dst=/prepared" in argument:\n'
                           '   fields = dict(part.split("=", 1) for part in argument.split(",") if "=" in part)\n'
                           '   target = Path(fields["src"])\n'
                           '   for name in ("packages.txt", "compiler.txt", "cmake.txt", "versions.txt", "external-state.json"):\n'
                           '    (target / name).write_text("fixture environment")\n')
        runtime.chmod(0o755)
        with patch.object(launcher.shutil, 'which', return_value=str(runtime)), \
             patch('sys.argv', ['ci', '--prepare']):
            self.assertEqual(launcher.main(), 0)
        self.assertEqual((prepared.with_name('ci-prepared.previous-1') / 'keep-me').read_text(), 'old evidence')
        self.assertTrue((prepared / 'manifest.json').is_file())

    def test_snapshot_preserves_current_inputs_and_omits_deleted_and_ignored(self):
        (self.root / 'edited').write_text('edited content')
        (self.root / 'deleted').unlink()
        (self.root / 'new space name').write_text('new content')
        (self.root / 'ignored').write_text('ignored content')
        target = Path(self.temporary.name) / 'snapshot'
        target.mkdir()
        untracked = launcher.snapshot(target)
        self.assertEqual(untracked, ['new space name'])
        self.assertEqual((target / 'edited').read_text(), 'edited content')
        self.assertEqual((target / 'new space name').read_text(), 'new content')
        self.assertEqual((target / 'space name').read_text(), 'original')
        self.assertFalse((target / 'deleted').exists())
        self.assertFalse((target / 'ignored').exists())
        self.assertTrue((target / 'executable').stat().st_mode & 0o111)
        self.assertTrue((target / 'link').is_symlink())
        self.assertEqual(os.readlink(target / 'link'), 'edited')

    def test_rootless_podman_preserves_user_mapping_and_read_only_input(self):
        self.prepare_fixture()
        runtime = Path(self.temporary.name) / 'podman'
        arguments = Path(self.temporary.name) / 'podman-arguments.json'
        runtime.write_text('#!/usr/bin/env python3\nimport json, sys\nfrom pathlib import Path\n'
                           'if sys.argv[1] == "--version": print("fake-podman")\n'
                           'else:\n'
                           ' accounts = {}\n'
                           ' for argument in sys.argv[1:]:\n'
                           '  if "dst=/etc/passwd," in argument or "dst=/etc/group," in argument:\n'
                           '   fields = dict(part.split("=", 1) for part in argument.split(",") if "=" in part)\n'
                           '   assert argument.endswith(",readonly")\n'
                           '   accounts[fields["dst"]] = Path(fields["src"]).read_text()\n'
                           '  if "dst=/output" in argument:\n'
                           '   assert not argument.endswith(",readonly")\n'
                           '   fields = dict(part.split("=", 1) for part in argument.split(",") if "=" in part)\n'
                           '   Path(fields["src"], "fixture-artifact").write_text("generated")\n'
                           f' Path({str(arguments)!r}).write_text(json.dumps([sys.argv[1:], accounts]))\n')
        runtime.chmod(0o755)
        with patch.object(launcher.shutil, 'which', side_effect=lambda name: str(runtime) if name == 'podman' else None), \
             patch.object(launcher.os, 'getuid', return_value=1000), \
             patch.object(launcher.os, 'getgid', return_value=1000), \
             patch('sys.argv', ['ci', '--lane', launcher.LANES[0]]):
            self.assertEqual(launcher.main(), 0)
        command, accounts = json.loads(arguments.read_text())
        self.assertIn('--userns=keep-id', command)
        self.assertEqual(command[command.index('--user') + 1], '1000:1000')
        self.assertIn('--pull=never', command)
        self.assertIn('--network=none', command)
        self.assertIn('/input/scripts/ci/lane.sh', command)
        self.assertTrue(any(a.endswith('dst=/prepared,readonly') for a in command))
        self.assertTrue(command[command.index('--mount') + 1].endswith(',dst=/input,readonly'))
        self.assertIn('ci:x:1000:1000:CI:/work/build/home:/bin/sh\n', accounts['/etc/passwd'])
        self.assertIn('ci:x:1000:\n', accounts['/etc/group'])
        artifact = next((self.root / 'build/ci').glob('*/artifacts/*/fixture-artifact'))
        self.assertEqual(artifact.read_text(), 'generated')
        self.assertEqual(artifact.stat().st_uid, os.getuid())

    def test_missing_runtime_fails_and_records_reason(self):
        with patch.object(launcher.shutil, 'which', return_value=None), patch('sys.argv', ['ci']):
            self.assertEqual(launcher.main(), 1)
        result = json.loads(next((self.root / 'build/ci').glob('*/results.json')).read_text())
        self.assertIn('Neither Docker nor Podman', result['error'])

    def test_every_failed_lane_fails_task_and_remaining_lanes_run(self):
        self.prepare_fixture()
        runtime = Path(self.temporary.name) / 'docker'
        runtime.write_text('#!/bin/sh\nif [ "$1" = --version ]; then echo fake-runtime; exit 0; fi\nexit 17\n')
        runtime.chmod(0o755)
        with patch.object(launcher.shutil, 'which', return_value=str(runtime)), patch('sys.argv', ['ci']):
            self.assertEqual(launcher.main(), 1)
        result = json.loads(next((self.root / 'build/ci').glob('*/results.json')).read_text())
        self.assertEqual(set(result['lanes']), set(launcher.LANES))
        self.assertTrue(all(lane['exit_code'] == 17 for lane in result['lanes'].values()))
        self.assertEqual((self.root / 'edited').read_text(), 'original')


if __name__ == '__main__':
    unittest.main()
