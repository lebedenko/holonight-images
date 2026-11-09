# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest

from profile import Harness, PHASES, parse_line, summarize


def row(variant='baseline', total=100, accepted=True):
    return dict(variant=variant, stage='measured', accepted=accepted, total_ns=total,
                fd_before=4, fd_after=4, events=[] if variant == 'baseline' else
                [dict(phase=p, path='', bytes=None, ns=1) for p in sorted(PHASES)])


class AccountingTests(unittest.TestCase):
    def test_missing_observations_remain_missing(self):
        report = summarize([row()], [], expected=2)
        self.assertEqual(report['variants']['baseline']['missing'], 1)
        self.assertIsNone(report['variants']['instrumented']['total_ns']['median'])
        self.assertIsNone(report['median_overhead_fraction'])
        self.assertEqual(report['attribution'], 'incomplete')

    def test_rejections_are_not_successful_timing_samples(self):
        report = summarize([row(accepted=False)], [], expected=1)
        self.assertEqual(report['variants']['baseline']['rejected'], 1)
        self.assertEqual(report['variants']['baseline']['total_ns']['n'], 0)
        self.assertFalse(report['complete'])
        self.assertFalse(parse_line(json.dumps(row(accepted=False)), False, False)['accepted'])
        with self.assertRaises(ValueError):
            parse_line(json.dumps(row(accepted=False)), False, True)

    def test_malformed_missing_and_truncated_telemetry(self):
        for value in ('{', '{}', 'null', json.dumps({**row('instrumented'), 'events': []})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_line(value, True, True)
        with self.assertRaises(ValueError):
            parse_line(json.dumps(row('instrumented')), True, True, {'usr/a': 12})

    def test_phase_accounting_does_not_invent_baseline_attribution(self):
        report = summarize([row(), row('instrumented')], [], expected=1)
        self.assertIsNone(report['variants']['baseline']['phase_coverage']['median'])
        self.assertEqual(report['variants']['instrumented']['phase_coverage']['median'], .07)
        self.assertEqual(report['variants']['instrumented']['phases_ns']['read_hash']['n'], 1)

    def test_overhead_both_directions_and_boundary(self):
        for total, label in [(110, 'within 10%'), (109, 'within 10%'), (111, 'materially perturbed'),
                             (89, 'materially perturbed'), (90, 'within 10%')]:
            with self.subTest(total=total):
                report = summarize([row(), row('instrumented', total)], [], expected=1)
                self.assertEqual(report['attribution'], label)
        report = summarize([row(), row('instrumented')], ['TimeoutError'], expected=1)
        self.assertEqual(report['attribution'], 'incomplete')

    def test_fd_leak_and_excessive_phase_coverage_rejected(self):
        for value in ({**row(), 'fd_after': 5}, row('instrumented', total=1)):
            with self.assertRaises(ValueError):
                parse_line(json.dumps(value), bool(value['events']), True)

    def test_timeout_and_truncated_child_are_reaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'child'
            script.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdin.readline()\nprint("{", end="", flush=True)\n')
            script.chmod(0o755)
            harness = Harness(script, root / 'errors', seconds=0)
            try:
                with self.assertRaises(TimeoutError):
                    harness.request(root)
            finally:
                self.assertTrue(harness.close()['reaped'])
            harness = Harness(script, root / 'errors')
            try:
                with self.assertRaisesRegex(ValueError, 'truncated'):
                    harness.request(root)
            finally:
                closed = harness.close()
                self.assertTrue(closed['reaped'])
                self.assertTrue(closed['proc_absent'])
                self.assertEqual(closed['trailing_telemetry'], '{')


if __name__ == '__main__':
    unittest.main()
