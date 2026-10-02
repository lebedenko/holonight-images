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
        self.root = Path(self.temporary.name) / 'repo'
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
        self.patcher = patch.object(launcher, 'ROOT', self.root)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

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

    def test_missing_runtime_fails_and_records_reason(self):
        with patch.object(launcher.shutil, 'which', return_value=None), patch('sys.argv', ['ci']):
            self.assertEqual(launcher.main(), 1)
        result = json.loads(next((self.root / 'build/ci').glob('*/results.json')).read_text())
        self.assertIn('Neither Docker nor Podman', result['error'])

    def test_every_failed_lane_fails_task_and_remaining_lanes_run(self):
        scripts = self.root / 'scripts/ci'
        scripts.mkdir(parents=True)
        (scripts / 'images.json').write_text('{"build":"build@sha256:fixture","licensing":"reuse@sha256:fixture"}')
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
