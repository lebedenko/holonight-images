#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import sys
import tempfile
import unittest
import run


class RunnerTests(unittest.TestCase):
    def row(self):
        return dict(completed=True, digest='a' * 64, position=7, at_end=True,
                    file_error=-1, error='Unknown error', reads=[])

    def test_acceptance_and_digest_mismatch_stop(self):
        for field, value in [('completed', False), ('digest', 'b' * 64)]:
            other = dict(self.row(), **{field: value})
            with self.assertRaisesRegex(ValueError, 'mismatch'):
                run.compare([self.row(), other])
        with self.assertRaisesRegex(ValueError, 'expected digest'):
            run.compare([self.row(), self.row()], 'c' * 64)

    def test_incomplete_results_rejected(self):
        for text in ('', '{', '{}', json.dumps({'completed': True}),
                     json.dumps(self.row()) + '\n' + json.dumps(self.row())):
            with self.assertRaises(ValueError):
                run.parse(text)
        self.assertEqual(run.parse(json.dumps(self.row())), self.row())

    def test_timeout_preserves_output_and_reaps(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            records = []
            with self.assertRaises(TimeoutError):
                run.child([sys.executable, '-c',
                           'import time; print("partial", flush=True); time.sleep(60)'], out, records, seconds=.2)
            self.assertTrue(records[0]['timeout'])
            self.assertTrue(records[0]['reaped'])
            self.assertTrue(records[0]['proc_absent'])
            self.assertEqual((out / '0000.stdout').read_text(), 'partial\n')

    def test_overlay_preserves_guard_and_rejects_shape_changes(self):
        source = '#include "runtime.h"\n!file.open(QIODevice::ReadOnly) || !hash.addData(&file) ||\n'
        changed = run.overlay(source)
        self.assertIn('!file.open(QIODevice::ReadOnly) || !HashCorrectness::addData(hash, &file) ||', changed)
        for unexpected in ('', source + source):
            with self.assertRaises(ValueError):
                run.overlay(unexpected)


if __name__ == '__main__':
    unittest.main()
